import os
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import StringIO, BytesIO
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

try:
    from deep_translator import GoogleTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError:
    TRANSLATOR_AVAILABLE = False

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

st.set_page_config(page_title="Genius AI BOT | Huzar Intrastat & CBAM", page_icon="🚢", layout="wide")

DATA_DIR = "projects_data"
DB_FILE = os.path.join(DATA_DIR, "hs_database_v3.json")
IMG_DB_DIR = os.path.join(DATA_DIR, "db_images")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
if not os.path.exists(IMG_DB_DIR):
    os.makedirs(IMG_DB_DIR)

class StoredFile:
    def __init__(self, filepath, name):
        self.filepath = filepath
        self.name = name
        ext = name.split(".")[-1].lower()
        if ext in ["pdf"]: self.type = "application/pdf"
        elif ext in ["jpg", "jpeg"]: self.type = "image/jpeg"
        elif ext in ["png"]: self.type = "application/png"
        elif ext in ["xlsx", "xls"]: self.type = "spreadsheet"
        else: self.type = "unsupported"

    def getvalue(self):
        try:
            with open(self.filepath, "rb") as f:
                return f.read()
        except Exception:
            return b""

def load_companies_and_containers():
    data_struct = {}
    if not os.path.exists(DATA_DIR):
        return data_struct
    for company_name in os.listdir(DATA_DIR):
        comp_dir = os.path.join(DATA_DIR, company_name)
        if os.path.isdir(comp_dir) and company_name != "db_images":
            data_struct[company_name] = {}
            for container_no in os.listdir(comp_dir):
                cont_dir = os.path.join(comp_dir, container_no)
                if os.path.isdir(cont_dir):
                    json_path = os.path.join(cont_dir, "data.json")
                    c_data = {"out1": "", "out2": "", "out3": "", "calc_audit": "", "docs": [], "hs_approved": [], "cbam_data": "", "cbam_audit_result": ""}
                    if os.path.exists(json_path):
                        try:
                            with open(json_path, "r", encoding="utf-8") as f:
                                c_data.update(json.load(f))
                        except Exception:
                            pass
                    docs_dir = os.path.join(cont_dir, "docs")
                    if os.path.exists(docs_dir):
                        for fname in os.listdir(docs_dir):
                            fpath = os.path.join(docs_dir, fname)
                            sf = StoredFile(fpath, fname)
                            if sf.type != "unsupported":
                                c_data["docs"].append(sf)
                    data_struct[company_name][container_no] = c_data
    return data_struct

def save_container_data(company_name, container_no, data):
    cont_dir = os.path.join(DATA_DIR, company_name, container_no)
    if not os.path.exists(cont_dir):
        os.makedirs(cont_dir)
    json_path = os.path.join(cont_dir, "data.json")
    save_data = {
        "out1": data.get("out1", ""),
        "out2": data.get("out2", ""),
        "out3": data.get("out3", ""),
        "calc_audit": data.get("calc_audit", ""),
        "hs_approved": data.get("hs_approved", []),
        "cbam_data": data.get("cbam_data", ""),
        "cbam_audit_result": data.get("cbam_audit_result", "")
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)

def save_uploaded_files(company_name, container_no, uploaded_files):
    cont_dir = os.path.join(DATA_DIR, company_name, container_no)
    docs_dir = os.path.join(cont_dir, "docs")
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)
    saved_docs = []
    for f in uploaded_files:
        try:
            f_bytes = f.getvalue()
            if not f_bytes: continue
            if f.name.lower().endswith(".zip"):
                with zipfile.ZipFile(BytesIO(f_bytes)) as z:
                    for filename in z.namelist():
                        if filename.endswith('/') or '__MACOSX' in filename or filename.startswith('.'):
                            continue
                        file_data = z.read(filename)
                        base_name = os.path.basename(filename)
                        if not base_name: continue
                        fpath = os.path.join(docs_dir, base_name)
                        with open(fpath, "wb") as out:
                            out.write(file_data)
                        sf = StoredFile(fpath, base_name)
                        if sf.type != "unsupported":
                            saved_docs.append(sf)
            else:
                fpath = os.path.join(docs_dir, f.name)
                with open(fpath, "wb") as out:
                    out.write(f_bytes)
                sf = StoredFile(fpath, f.name)
                if sf.type != "unsupported":
                    saved_docs.append(sf)
        except Exception as e:
            st.error(f"Błąd zapisu pliku {f.name}: {str(e)}")
    return saved_docs

def delete_container_dir(company_name, container_no):
    import shutil
    cont_dir = os.path.join(DATA_DIR, company_name, container_no)
    if os.path.exists(cont_dir):
        shutil.rmtree(cont_dir)

def safe_generate_content(client, model_name, contents, max_retries=3, initial_delay=2):
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(model=model_name, contents=contents)
        except Exception as e:
            err_str = str(e)
            if "503" in err_str or "UNAVAILABLE" in err_str or "high demand" in err_str.lower():
                if attempt < max_retries - 1:
                    time.sleep(initial_delay * (attempt + 1))
                    continue
            raise e

def translate_text_google(text):
    if not text or not TRANSLATOR_AVAILABLE:
        return text
    try:
        translated = GoogleTranslator(source='auto', target='pl').translate(str(text))
        return translated if translated else text
    except Exception:
        return text

def load_hs_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_hs_database(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def update_hs_database_from_records(records, image_file=None):
    db = load_hs_database()
    updated_count = 0
    img_name = ""
    if image_file:
        try:
            img_bytes = image_file.getvalue()
            if img_bytes:
                img_name = f"prod_{int(time.time())}_{image_file.name}"
                img_path = os.path.join(IMG_DB_DIR, img_name)
                with open(img_path, "wb") as out:
                    out.write(img_bytes)
        except Exception:
            pass

    for r in records:
        prod_name = str(r.get("Nazwa Produktu", "")).strip()
        material = str(r.get("Skład Materiałowy", "")).strip()
        taric = str(r.get("Ostateczny Kod TARIC", r.get("TARIC_PROPOSED", ""))).strip()
        cn_desc = str(r.get("Oficjalny Opis CN", "")).strip()
        opt_trans = str(r.get("Opcjonalne Tłumaczenie", "")).strip()
        
        if prod_name and taric and taric != "nan":
            key = f"{prod_name}_{material}_{taric}".lower()
            db[key] = {
                "product_name": prod_name,
                "material": material,
                "taric": taric,
                "cn_description": cn_desc,
                "optional_translation": opt_trans,
                "image": img_name or r.get("Zdjęcie wzorca", "")
            }
            updated_count += 1
    if updated_count > 0:
        save_hs_database(db)
    return updated_count

def process_excel_all_sheets(f_bytes):
    try:
        xl = pd.ExcelFile(BytesIO(f_bytes))
        combined_str = ""
        for sheet_name in xl.sheet_names:
            df_sheet = xl.parse(sheet_name)
            if len(df_sheet) > 1000:
                df_sheet = df_sheet.head(1000)
            combined_str += f"\n=== ZAKŁADKA / ARKUSZ: {sheet_name} ===\n" + df_sheet.to_string() + "\n"
        return combined_str
    except Exception as e:
        return f"[Błąd odczytu pliku Excel: {str(e)}]"

def process_intrastat_dataframe(text_data):
    clean_csv = text_data.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
    valid_lines = [line for line in clean_csv.split('\n') if line.count(';') >= 5 or "Nr_Faktury" in line or "Faktura" in line]
    if not valid_lines:
        return pd.DataFrame(columns=["Kontrahent", "NumerDokumentu", "DataWystawienia", "NIP", "Wartosc", "Waluta"])
    try:
        df = pd.read_csv(StringIO("\n".join(valid_lines)), sep=";", on_bad_lines='skip')
        for col in ["Ilosc_Sztuk", "Masa_Netto_KG", "Wartosc_PLN"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(",", ".").str.extract(r"(\d+\.?\d*)")[0].astype(float).fillna(0)
        
        if "Nr_Faktury" in df.columns:
            df["Nr_Faktury"] = df["Nr_Faktury"].astype(str).str.strip()
        if "Kod_CN" in df.columns:
            df["Kod_CN"] = df["Kod_CN"].astype(str).str.replace(r"\D", "", regex=True).str[:8]

        mapped_data = []
        for _, r in df.iterrows():
            mapped_data.append({
                "Kontrahent": str(r.get("Sprzedawca_Nazwa", r.get("Kontrahent", ""))),
                "NumerDokumentu": str(r.get("Nr_Faktury", r.get("NumerDokumentu", ""))),
                "DataWystawienia": str(r.get("Data_Faktury", r.get("DataWystawienia", ""))),
                "NIP": str(r.get("Sprzedawca_NIP", r.get("NIP", ""))),
                "Wartosc": float(r.get("Wartosc_PLN", r.get("Wartosc", 0))),
                "Waluta": "PLN",
                "Kod_CN": str(r.get("Kod_CN", "")),
                "Opis_Towaru": str(r.get("Opis_Towaru", "")),
                "Ilosc_Sztuk": float(r.get("Ilosc_Sztuk", 0)),
                "Masa_Netto_KG": float(r.get("Masa_Netto_KG", 0))
            })
        
        df_final = pd.DataFrame(mapped_data)
        if "NumerDokumentu" in df_final.columns:
            df_final = df_final.groupby(["NumerDokumentu"], as_index=False).agg({
                "Kontrahent": "first",
                "DataWystawienia": "first",
                "NIP": "first",
                "Wartosc": "sum",
                "Waluta": "first",
                "Kod_CN": lambda x: ", ".join(sorted(set(str(v) for v in x if pd.notna(v) and str(v).strip() != ''))),
                "Opis_Towaru": lambda x: " | ".join(sorted(set(str(v) for v in x if pd.notna(v) and str(v).strip() != ''))),
                "Ilosc_Sztuk": "sum",
                "Masa_Netto_KG": "sum"
            })
        return df_final
    except Exception:
        return pd.DataFrame()

def generate_huzarfaktury_xml(df):
    root = ET.Element("TFakturyHS")
    for _, row in df.iterrows():
        faktura = ET.SubElement(root, "Faktura")
        rodzaj_elem = ET.SubElement(faktura, "RodzajDokumentu")
        rodzaj_elem.text = "WDT"
        for col in df.columns:
            val = str(row[col]) if pd.notna(row[col]) else ""
            child = ET.SubElement(faktura, col)
            child.text = val
    rough_string = ET.tostring(root, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8")

def process_stage_2_dataframe(out2_text):
    clean_csv = out2_text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
    valid_lines = []
    for line in clean_csv.split('\n'):
        if line.count(';') >= 4 or "POS" in line or "pos" in line or "Product" in line:
            valid_lines.append(line)
    
    if not valid_lines:
        return pd.DataFrame(columns=["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"])
        
    try:
        df_raw = pd.read_csv(StringIO("\n".join(valid_lines)), sep=";", on_bad_lines='skip')
    except Exception:
        return pd.DataFrame()
    
    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    
    for col in df_raw.select_dtypes(include=['object']).columns:
        df_raw[col] = df_raw[col].astype(str).str.strip()

    if "POS" not in df_raw.columns and "pos" in df_raw.columns:
        df_raw["POS"] = df_raw["pos"]
    elif "POS" not in df_raw.columns:
        df_raw["POS"] = range(1, len(df_raw) + 1)

    if "Product_Name" not in df_raw.columns:
        for possible in ["Nazwa", "Product", "Towar", "Description"]:
            if possible in df_raw.columns:
                df_raw["Product_Name"] = df_raw[possible]
                break
        if "Product_Name" not in df_raw.columns:
            df_raw["Product_Name"] = "Towar"

    if "Material" not in df_raw.columns:
        for possible in ["Skład", "Material", "Materiały"]:
            if possible in df_raw.columns:
                df_raw["Material"] = df_raw[possible]
                break
        if "Material" not in df_raw.columns:
            df_raw["Material"] = "N/D"

    if "Waluta" not in df_raw.columns:
        df_raw["Waluta"] = "EUR"

    num_cols = ["CTNS", "Quantity", "NW_KGS", "GW_KGS", "Amount"]
    for col in num_cols:
        if col in df_raw.columns:
            df_raw[col] = df_raw[col].astype(str).str.replace(",", ".").str.extract(r"(\d+\.?\d*)")[0].astype(float).fillna(0)
        else:
            df_raw[col] = 0.0
    
    df_raw["POS"] = df_raw["POS"].astype(str)
    df_raw["Clean_Name"] = df_raw["Product_Name"].astype(str).str.strip().str.lower()
    df_raw["Clean_Mat"] = df_raw["Material"].astype(str).str.strip().str.lower()

    if "HS_CODE" in df_raw.columns:
        df_raw["HS_CODE"] = df_raw["HS_CODE"].astype(str).str.replace(r"\D", "", regex=True).str[:8]
    else:
        df_raw["HS_CODE"] = ""

    grouped = df_raw.groupby(["Clean_Name", "Clean_Mat", "Waluta"], as_index=False).agg({
        "POS": lambda x: ", ".join(sorted(set(x), key=lambda v: int(v) if str(v).isdigit() else v)),
        "Product_Name": "first",
        "Material": "first",
        "HS_CODE": lambda x: " | ".join(sorted(set(str(v) for v in x if pd.notna(v) and str(v).strip() != '' and str(v).lower() != 'nan'))),
        "CTNS": "sum",
        "Quantity": "sum",
        "NW_KGS": "sum",
        "GW_KGS": "sum",
        "Amount": "sum"
    })
    
    grouped["pos"] = range(1, len(grouped) + 1)
    grouped = grouped[["pos", "POS", "Product_Name", "Material", "HS_CODE", "CTNS", "Quantity", "NW_KGS", "GW_KGS", "Amount", "Waluta"]]
    grouped.columns = ["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"]
    return grouped

def parse_stage_3_csv(csv_text):
    clean_csv = csv_text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
    valid_lines = []
    for line in clean_csv.split('\n'):
        if line.count(';') >= 5 or "pos;" in line or "POS;" in line:
            valid_lines.append(line)
    try:
        return pd.read_csv(StringIO("\n".join(valid_lines)), sep=";", on_bad_lines='skip')
    except Exception:
        rows = []
        for line in valid_lines[1:]:
            parts = line.split(';')
            if len(parts) >= 6:
                rows.append({
                    "pos": parts[0],
                    "Invoice Positions": parts[1] if len(parts) > 1 else "",
                    "Nazwa Produktu": parts[2] if len(parts) > 2 else "",
                    "Skład Materiałowy": parts[3] if len(parts) > 3 else "",
                    "Opcjonalne Tłumaczenie": parts[4] if len(parts) > 4 else "",
                    "TARIC_PROPOSED": parts[5] if len(parts) > 5 else "",
                    "CN_HS_CODE": parts[6] if len(parts) > 6 else "",
                    "Oficjalny Opis CN": parts[7] if len(parts) > 7 else ""
                })
        return pd.DataFrame(rows)

class CustomPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(26, 54, 93)
        self.cell(0, 8, 'RAPORT KONTROLI FORMALNEJ I AUDYTU CELNEGO', ln=1)
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(74, 85, 104)
        self.cell(0, 5, 'Genius AI BOT | Genius Logistics Sp. z o.o.', ln=1)
        self.set_draw_color(43, 108, 176)
        self.set_line_width(0.6)
        self.line(10, 24, 200, 24)
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(113, 128, 150)
        self.cell(0, 8, f'Strona {self.page_no()} | Genius Logistics Sp. z o.o.', align='C')

class CBAMCustomPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(26, 54, 93)
        self.cell(0, 8, 'RAPORT ANALIZY I AUDYTU CBAM', ln=1)
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(74, 85, 104)
        self.cell(0, 5, 'Genius AI BOT | Unijny Mechanizm Dostosowywania Cen na Granicach', ln=1)
        self.set_draw_color(43, 108, 176)
        self.set_line_width(0.6)
        self.line(10, 24, 200, 24)
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(113, 128, 150)
        self.cell(0, 8, f'Strona {self.page_no()} | Genius Logistics Sp. z o.o.', align='C')

def generate_formal_pdf_report(container_no, markdown_content):
    if not FPDF_AVAILABLE: return None
    pdf = CustomPDF()
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_fill_color(235, 248, 255)
    pdf.set_draw_color(49, 130, 206)
    pdf.rect(12, 26, 186, 10, style='DF')
    pdf.set_xy(14, 28)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(44, 82, 130)
    clean_meta = f'KONTENER: {container_no} | STATUS: AUDYT ZAKONCZONY'
    pdf.cell(0, 6, clean_meta.encode('latin-1', 'replace').decode('latin-1'), ln=1)
    pdf.ln(6)
    lines = markdown_content.split('\n')
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            pdf.ln(2)
            continue
        clean_line = re.sub(r'[^\x00-\x7F\xC0-\xFF]', '', clean_line).strip()
        if not clean_line: continue
        if clean_line.startswith('###'):
            pdf.ln(3)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(44, 82, 130)
            txt = clean_line.replace('###', '').strip().encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 5, txt)
            pdf.ln(1)
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
        elif clean_line.startswith('-') or clean_line.startswith('*'):
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
            text = clean_line[1:].strip()
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
            txt = f' - {text}'.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 4.5, txt)
        else:
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_line)
            txt = text.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 4.5, txt)
    
    # Bezpieczne zwracanie bajtów PDF przez wywołanie output(dest='S').encode('latin1')
    try:
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            return pdf_output.encode('latin-1', 'replace')
        return pdf_output
    except Exception:
        return bytes(pdf.output())

def generate_cbam_pdf_report(company_name, markdown_content):
    if not FPDF_AVAILABLE: return None
    pdf = CBAMCustomPDF()
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_fill_color(235, 248, 255)
    pdf.set_draw_color(49, 130, 206)
    pdf.rect(12, 26, 186, 10, style='DF')
    pdf.set_xy(14, 28)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(44, 82, 130)
    clean_meta = f'FIRMA: {company_name} | RAPORT SPRAWOZDAWCZY CBAM'
    pdf.cell(0, 6, clean_meta.encode('latin-1', 'replace').decode('latin-1'), ln=1)
    pdf.ln(6)
    lines = markdown_content.split('\n')
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            pdf.ln(2)
            continue
        clean_line = re.sub(r'[^\x00-\x7F\xC0-\xFF]', '', clean_line).strip()
        if not clean_line: continue
        if clean_line.startswith('###'):
            pdf.ln(3)
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_text_color(44, 82, 130)
            txt = clean_line.replace('###', '').strip().encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 5, txt)
            pdf.ln(1)
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
        elif clean_line.startswith('-') or clean_line.startswith('*'):
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
            text = clean_line[1:].strip()
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
            txt = f' - {text}'.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 4.5, txt)
        else:
            pdf.set_font('Helvetica', '', 9)
            pdf.set_text_color(45, 55, 72)
            text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_line)
            txt = text.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(186, 4.5, txt)
            
    try:
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            return pdf_output.encode('latin-1', 'replace')
        return pdf_output
    except Exception:
        return bytes(pdf.output())

def call_ai_chunked_stage2(client, model_name, base_prompt, full_dataframe_text):
    lines = full_dataframe_text.strip().split('\n')
    if len(lines) <= 150:
        res = safe_generate_content(client, model_name, [base_prompt, full_dataframe_text])
        return res.text
    
    header = lines[0]
    data_lines = lines[1:]
    chunk_size = 150
    chunks = [data_lines[i:i + chunk_size] for i in range(0, len(data_lines), chunk_size)]
    
    combined_csv_rows = []
    for idx, chunk in enumerate(chunks):
        chunk_text = header + "\n" + "\n".join(chunk)
        chunk_prompt = (
            f"{base_prompt}\n"
            f"(UWAGA: To jest paczka {idx+1} z {len(chunks)}. Przetwórz wyłącznie poniższe wiersze i zwróć dane w formacie CSV z nagłówkiem)."
        )
        try:
            res = safe_generate_content(client, model_name, [chunk_prompt, chunk_text])
            clean_res = res.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
            res_lines = clean_res.split('\n')
            for r_idx, r_line in enumerate(res_lines):
                if r_idx == 0 and ("POS;" in r_line or "pos;" in r_line):
                    if not combined_csv_rows:
                        combined_csv_rows.append(r_line)
                else:
                    if r_line.strip() and r_line.count(';') >= 4:
                        combined_csv_rows.append(r_line)
        except Exception as e:
            st.warning(f"Ostrzeżenie przy paczce {idx+1}: {str(e)}")
            
    return "\n".join(combined_csv_rows)

def call_ai_chunked_stage3(client, model_name, summary_df):
    records = summary_df.to_dict(orient="records")
    chunk_size = 100
    chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]
    
    all_t3_rows = []
    header_str = "pos;Invoice Positions;Nazwa Produktu;Skład Materiałowy;Opcjonalne Tłumaczenie;TARIC_PROPOSED;CN_HS_CODE;Oficjalny Opis CN;Reasoning"
    
    for idx, chunk in enumerate(chunks):
        sub_df = pd.DataFrame(chunk)
        chunk_summary = sub_df[["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE"]].to_csv(index=False, sep=";")
        p3_prompt = (
            "Jesteś agentem celnym w Genius Logistics. Oto wycinek ZBITYCH pozycji towarowych (paczka "
            f"{idx+1} z {len(chunks)}):\n"
            f"{chunk_summary}\n\n"
            "Przeanalizuj i dokonaj taryfikacji WYŁĄCZNIE dla powyższych pozycji.\n"
            "ZACHOWAJ ORYGINALNĄ Nazwę Produktu oraz Skład Materiałowy w osobnych kolumnach.\n"
            "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
            f"{header_str}"
        )
        try:
            res = safe_generate_content(client, model_name, [p3_prompt])
            clean_res = res.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
            res_lines = clean_res.split('\n')
            for r_idx, r_line in enumerate(res_lines):
                if r_idx == 0 and "pos;" in r_line:
                    if not all_t3_rows:
                        all_t3_rows.append(r_line)
                else:
                    if r_line.strip() and r_line.count(';') >= 4:
                        all_t3_rows.append(r_line)
        except Exception as e:
            st.warning(f"Ostrzeżenie taryfikacji w paczce {idx+1}: {str(e)}")
            
    return "\n".join(all_t3_rows)

# --- SIDEBAR & STEROWANIE ---
if "company_data" not in st.session_state:
    st.session_state.company_data = load_companies_and_containers()

if "current_company" not in st.session_state:
    if st.session_state.company_data:
        st.session_state.current_company = list(st.session_state.company_data.keys())[0]
    else:
        st.session_state.current_company = None

if "current_container" not in st.session_state:
    if st.session_state.current_company and st.session_state.company_data[st.session_state.current_company]:
        st.session_state.current_container = list(st.session_state.company_data[st.session_state.current_company].keys())[0]
    else:
        st.session_state.current_container = None

DEFAULT_KEY = "AQ.Ab8RN6LNsWIfhgnWWSVYIZEM2O_MG3HL2o9hFVmjexwfw8RMdg"

st.sidebar.markdown("### 🚢 Genius AI BOT")
st.sidebar.markdown("Enterprise Logistics Platform")
api_key = st.sidebar.text_input("Klucz API Gemini", value=DEFAULT_KEY, type="password")
selected_model = st.sidebar.selectbox("Model API", ["gemini-3.6-flash"])

st.sidebar.markdown("---")

# GLOBALNY WYBÓR FIRMY (Krzyżowy dla całej aplikacji)
st.sidebar.markdown("### 🏢 Globalny Wybór Firmy")
new_comp = st.sidebar.text_input("Nazwa Nowej Firmy", placeholder="np. Firma XYZ").strip()
if st.sidebar.button("+ Dodaj Firmę", use_container_width=True):
    if new_comp:
        if new_comp not in st.session_state.company_data:
            st.session_state.company_data[new_comp] = {}
        st.session_state.current_company = new_comp
        st.session_state.current_container = None
        st.sidebar.success(f"Aktywowano firmę: {new_comp}")
        st.rerun()

if st.session_state.company_data:
    comp_list = list(st.session_state.company_data.keys())
    curr_comp_idx = comp_list.index(st.session_state.current_company) if st.session_state.current_company in comp_list else 0
    selected_comp = st.sidebar.selectbox("📂 Aktywna Firma", options=comp_list, index=curr_comp_idx)
    
    if selected_comp != st.session_state.current_company:
        st.session_state.current_company = selected_comp
        containers_in_comp = list(st.session_state.company_data[selected_comp].keys())
        st.session_state.current_container = containers_in_comp[0] if containers_in_comp else None
        st.rerun()
else:
    st.sidebar.warning("Brak zdefiniowanych firm. Dodaj firmę powyżej.")

st.sidebar.markdown("---")
app_mode = st.sidebar.radio(
    "📌 Wybierz Moduł Pracy:",
    [
        "🚢 Odprawy i Taryfikacja Kontenerów", 
        "📦 Dedykowany Generator INTRASTAT (Huzar)", 
        "🗄️ Wizualna Baza Kodów HS",
        "🇪🇺 Moduł CBAM (Kalkulator Emisji)"
    ]
)
st.sidebar.markdown("---")

# ==============================================================================
# MODUŁ 4: CBAM (KALKULATOR WAG I EMISJI)
# ==============================================================================
if app_mode == "🇪🇺 Moduł CBAM (Kalkulator Emisji)":
    st.title("🇪🇺 Moduł CBAM — Unijny Mechanizm Dostosowywania Cen na Granicach")
    st.caption("Obliczanie wag, weryfikacja progu 50 ton rocznie oraz audyt asortymentu podlegającego pod dyrektywę CBAM.")

    if not st.session_state.current_company:
        st.warning("⚠️ Najpierw dodaj i wybierz firmę w panelu bocznym!")
    else:
        st.info(f"📂 **Aktywna Firma w module CBAM:** `{st.session_state.current_company}`")

    cbam_tab = st.radio(
        "Wybierz Etap CBAM",
        ["📊 Etap 1: Kalkulator z Taryfikacji i Wag (Na bazie Kontenera)", "🔍 Etap 2: Niezależny Audyt z Własnych Dokumentów i Odprawy"],
        horizontal=True
    )
    st.markdown("---")

    if cbam_tab == "📊 Etap 1: Kalkulator z Taryfikacji i Wag (Na bazie Kontenera)":
        st.subheader("📊 Etap 1: Przesiew i Kalkulacja Wagi CBAM z Zatwierdzonego Kontenera")
        st.info("Ten etap korzysta z zatwierdzonych kodów HS oraz mas z aktywnego kontenera wybranej firmy.")

        if not st.session_state.current_company or not st.session_state.company_data.get(st.session_state.current_company):
            st.warning("⚠️ Wybrana firma nie posiada kontenerów!")
        else:
            cur_comp = st.session_state.current_company
            containers_in_comp = list(st.session_state.company_data[cur_comp].keys())
            selected_cbam_cont = st.selectbox("Wybierz kontener dla firmy do analizy CBAM", options=containers_in_comp)
            
            proj_data = st.session_state.company_data[cur_comp][selected_cbam_cont]
            
            if not proj_data.get("hs_approved"):
                st.warning(f"⚠️ Brak zatwierdzonych kodów HS dla kontenera `{selected_cbam_cont}` w firmie `{cur_comp}`. Przejdź do modułu kontenerów i zatwierdź kody w Etapie 3.")
            else:
                df_approved = pd.DataFrame(proj_data["hs_approved"])
                st.markdown(f"**Firma:** `{cur_comp}` | **Kontener:** `{selected_cbam_cont}` | Liczba pozycji zatwierdzonych: `{len(df_approved)}`")

                if st.button("⚡ Uruchom Analizę i Kalkulację Wagi CBAM (Etap 1)", type="primary"):
                    client = genai.Client(api_key=api_key)
                    recs = df_approved.to_dict(orient="records")
                    prompt_cbam_e1 = (
                        "Jesteś ekspertem ds. CBAM w unijnej agencji celnej.\n"
                        "Oto zatwierdzone pozycje towarowe dla kontenera:\n"
                        f"{json.dumps(recs, ensure_ascii=False, indent=2)}\n\n"
                        "Przeanalizuj każdy kod TARIC / HS pod kątem unijnego rozporządzenia CBAM (stal, żelazo, aluminium, nawozy, wodór, energia elektryczna).\n"
                        "Dla każdej pozycji określ czy podlega pod CBAM (TAK / NIE), podaj kategorię CBAM oraz oszacuj masę netto podlegającą pod dyrektywę.\n"
                        "Zwróć wynik w przejrzystej tabeli Markdown z kolumnami: [Nazwa Produktu | Kod TARIC | Masa Netto (kg) | Czy CBAM? | Kategoria CBAM | Uwagi]."
                    )
                    with st.spinner("Analiza kodów i wyliczanie wag CBAM..."):
                        res_cbam1 = safe_generate_content(client, selected_model, prompt_cbam_e1)
                        proj_data["cbam_data"] = res_cbam1.text
                        save_container_data(cur_comp, selected_cbam_cont, proj_data)
                        st.success("✅ Analiza Etapu 1 zakończona pomyślnie!")
                        st.rerun()

                if proj_data.get("cbam_data"):
                    st.markdown("### 📋 Wynik Analizy CBAM (Etap 1)")
                    st.markdown(proj_data["cbam_data"])
                    st.markdown("---")
                    if FPDF_AVAILABLE:
                        cbam_pdf_bytes = generate_cbam_pdf_report(cur_comp, proj_data["cbam_data"])
                        st.download_button("📄 Pobierz Raport CBAM (Etap 1) w formacie PDF", data=cbam_pdf_bytes, file_name=f"Raport_CBAM_Etap1_{cur_comp}_{selected_cbam_cont}.pdf", mime="application/pdf", use_container_width=True)

    else:
        st.subheader("🔍 Etap 2: Niezależny Audyt i Weryfikacja Progu 50 Ton CBAM z Własnych Dokumentów")
        st.info(f"Wgraj niezależne pliki handlowe lub odprawę celną dla aktywnej firmy: **{st.session_state.current_company}**. System zsumuje masę i sprawdzi próg zwolnienia *de minimis* (50 ton rocznie).")

        if "cbam_independent_docs" not in st.session_state:
            st.session_state.cbam_independent_docs = []

        uploaded_cbam_indep = st.file_uploader(
            "Wgraj pliki do niezależnej analizy CBAM (PDF / Excel / ZIP / Skan Odprawy lub Faktury)",
            type=["zip", "pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="cbam_indep_files"
        )

        if uploaded_cbam_indep:
            saved_indep = []
            for f in uploaded_cbam_indep:
                try:
                    f_bytes = f.getvalue()
                    if not f_bytes: continue
                    if f.name.lower().endswith(".zip"):
                        with zipfile.ZipFile(BytesIO(f_bytes)) as z:
                            for filename in z.namelist():
                                if filename.endswith('/') or '__MACOSX' in filename or filename.startswith('.'):
                                    continue
                                file_data = z.read(filename)
                                base_name = os.path.basename(filename)
                                if not base_name: continue
                                class ZipWrapper:
                                    def __init__(self, name, data):
                                        self.name = name
                                        self._data = data
                                    def getvalue(self):
                                        return self._data
                                saved_indep.append(ZipWrapper(base_name, file_data))
                    else:
                        saved_indep.append(f)
                except Exception as e:
                    st.error(f"Błąd pliku {f.name}: {str(e)}")
            st.session_state.cbam_independent_docs = saved_indep
            st.success(f"✅ Wgrano i załączono {len(saved_indep)} niezależnych plików do analizy CBAM dla firmy {st.session_state.current_company}.")

        if st.session_state.cbam_independent_docs:
            st.write("📂 **Załączone niezależnie pliki:** " + ", ".join([d.name for d in st.session_state.cbam_independent_docs]))

            if st.button("🚀 Uruchom Niezależny Audyt CBAM i Sprawdź Próg 50 Ton", type="primary", use_container_width=True):
                if not api_key:
                    st.error("Wpisz klucz API Gemini w panelu bocznym.")
                elif not st.session_state.current_company:
                    st.error("Wybierz najpierw firmę w panelu bocznym.")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        prompt_cbam_indep_audit = (
                            f"Jesteś niezależnym biegłym ds. audytu celnego i sprawozdawczości CBAM dla firmy: {st.session_state.current_company}.\n"
                            "Przeanalizuj poniższe dane źródłowe ze wszystkich wgranych dokumentów i zakładek Excel:\n"
                            "1. Zidentyfikuj pozycje towarowe objęte unijnym rozporządzeniem CBAM (stal, żelazo, aluminium, nawozy itp.).\n"
                            "2. Dokładnie zsumuj i wylicz łączną masę netto (w kg oraz tonach) towarów CBAM w dostarczonych dokumentach.\n"
                            "3. Sprawdź, czy łączna masa przekracza ustawowy próg roczny de minimis wynoszący 50 ton.\n"
                            "4. Stwórz szczegółową tabelę z podziałem na produkty, kody TARIC oraz masy netto, a na końcu sformułuj jednoznaczny wniosek: czy firma przekracza próg 50 ton (TAK / NIE) i jakie ma obowiązki sprawozdawcze."
                        )
                        contents = [prompt_cbam_indep_audit]
                        for f in st.session_state.cbam_independent_docs:
                            f_bytes = f.getvalue()
                            ext = f.name.split(".")[-1].lower()
                            if ext in ["xlsx", "xls"]:
                                excel_text = process_excel_all_sheets(f_bytes)
                                contents.append(f"\n--- ZAWARTOŚĆ PLIKU EXCEL ({f.name} - wszystkie zakładki) ---\n" + excel_text + "\n")
                            elif ext == "pdf":
                                try:
                                    contents.append(types.Part.from_bytes(data=f_bytes, mime_type="application/pdf"))
                                except Exception:
                                    pass
                            elif ext in ["jpg", "jpeg"]:
                                contents.append(types.Part.from_bytes(data=f_bytes, mime_type="image/jpeg"))
                            elif ext == "png":
                                contents.append(types.Part.from_bytes(data=f_bytes, mime_type="application/png"))

                        with st.spinner(f"Niezależna analiza wgranych dokumentów i liczenie progu 50 ton dla firmy {st.session_state.current_company}..."):
                            res_indep = safe_generate_content(client, selected_model, contents)
                            st.session_state.cbam_indep_result = res_indep.text
                            st.success("✅ Niezależny audyt CBAM zakończony pomyślnie!")
                    except Exception as e:
                        st.error(f"Błąd podczas niezależnego audytu: {str(e)}")

        if "cbam_indep_result" in st.session_state and st.session_state.cbam_indep_result:
            st.markdown("---")
            st.markdown(f"### 📋 Wynik Niezależnego Audytu CBAM dla Firmy: {st.session_state.current_company}")
            st.markdown(st.session_state.cbam_indep_result)
            st.markdown("---")
            if FPDF_AVAILABLE:
                cbam_indep_pdf_bytes = generate_cbam_pdf_report(st.session_state.current_company, st.session_state.cbam_indep_result)
                st.download_button("📄 Pobierz Niezależny Raport CBAM (Etap 2) w formacie PDF", data=cbam_indep_pdf_bytes, file_name=f"Raport_CBAM_Etap2_{st.session_state.current_company}.pdf", mime="application/pdf", use_container_width=True)

# ==============================================================================
# MODUŁ 3: WIZUALNA BAZA KODÓW HS
# ==============================================================================
elif app_mode == "🗄️ Wizualna Baza Kodów HS":
    st.title("🗄️ Wizualna Baza Wiedzy (Nazwa + Skład Materiału + Google Translate + Kod CN)")
    st.caption("Przeglądaj, wyszukuj, importuj z plików PDF i zarządzaj wzorcami towarowymi zapamiętanymi przez system.")

    hs_db = load_hs_database()
    st.info(f"Aktualna liczba wzorców w bazie: **{len(hs_db)}**")

    st.markdown("### 📥 Masowy Import Historycznych Wzorców z Plików PDF lub Excel")
    st.caption("Wgraj pliki PDF lub pliki Excel zawierające wszystkie zakładki. Sztuczna inteligencja automatycznie je odczyta i dopisze do bazy wzorców.")
    
    uploaded_import_files = st.file_uploader("Wgraj pliki z historycznymi taryfikacjami", type=["pdf", "xlsx", "xls", "json"], accept_multiple_files=True, key="db_import_pdf_files")
    
    if uploaded_import_files:
        if st.button("⚡ Przetwarzaj pliki i zasil Bazę Wzorców", type="primary"):
            if not api_key:
                st.error("Wpisz klucz API Gemini w panelu bocznym.")
            else:
                try:
                    db_current = load_hs_database()
                    total_imported = 0
                    client = genai.Client(api_key=api_key)
                    
                    for imp_f in uploaded_import_files:
                        f_bytes = imp_f.getvalue()
                        ext = imp_f.name.split(".")[-1].lower()
                        
                        if ext == "json":
                            imported_json = json.loads(f_bytes.decode('utf-8'))
                            if isinstance(imported_json, dict):
                                db_current.update(imported_json)
                                total_imported += len(imported_json)
                        elif ext in ["xlsx", "xls"]:
                            excel_text = process_excel_all_sheets(f_bytes)
                            prompt_excel_import = (
                                "Jesteś analitykiem celnym. Przeanalizuj poniższe dane z pliku Excel (wszystkie zakładki):\n"
                                f"{excel_text}\n\n"
                                "Wyciągnij każdą pozycję taryfową i zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) w pierwszej linii bez dodatkowego markdown:\n"
                                "Nazwa_Produktu;Sklad_Materialowy;Kod_TARIC;Opis_CN;Tlumaczenie"
                            )
                            with st.spinner(f"Odczytywanie pliku Excel: {imp_f.name}..."):
                                res_exc = safe_generate_content(client, selected_model, [prompt_excel_import])
                                clean_csv_exc = res_exc.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
                                for line in clean_csv_exc.split('\n'):
                                    if "Nazwa_Produktu" in line or line.count(';') < 2:
                                        continue
                                    parts = line.split(';')
                                    if len(parts) >= 3:
                                        p_name = parts[0].strip()
                                        mat = parts[1].strip()
                                        taric = parts[2].strip()
                                        cn_desc = parts[3].strip() if len(parts) > 3 else ""
                                        opt_trans = parts[4].strip() if len(parts) > 4 else ""
                                        
                                        if p_name and taric and taric != "nan":
                                            key = f"{p_name}_{mat}_{taric}".lower()
                                            db_current[key] = {
                                                "product_name": p_name,
                                                "material": mat,
                                                "taric": taric,
                                                "cn_description": cn_desc,
                                                "optional_translation": opt_trans,
                                                "image": ""
                                            }
                                            total_imported += 1
                        elif ext == "pdf":
                            prompt_pdf_import = (
                                "Jesteś analitykiem celnym. Przeanalizuj ten dokument PDF zawierający historyczne taryfikacje towarów.\n"
                                "Wyciągnij każdą pozycję i zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) w pierwszej linii bez dodatkowego markdown:\n"
                                "Nazwa_Produktu;Sklad_Materialowy;Kod_TARIC;Opis_CN;Tlumaczenie"
                            )
                            try:
                                contents = [prompt_pdf_import, types.Part.from_bytes(data=f_bytes, mime_type="application/pdf")]
                                with st.spinner(f"Odczytywanie pliku PDF: {imp_f.name}..."):
                                    res_pdf = safe_generate_content(client, selected_model, contents)
                                    clean_csv_pdf = res_pdf.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
                                    for line in clean_csv_pdf.split('\n'):
                                        if "Nazwa_Produktu" in line or line.count(';') < 2:
                                            continue
                                        parts = line.split(';')
                                        if len(parts) >= 3:
                                            p_name = parts[0].strip()
                                            mat = parts[1].strip()
                                            taric = parts[2].strip()
                                            cn_desc = parts[3].strip() if len(parts) > 3 else ""
                                            opt_trans = parts[4].strip() if len(parts) > 4 else ""
                                            
                                            if p_name and taric and taric != "nan":
                                                key = f"{p_name}_{mat}_{taric}".lower()
                                                db_current[key] = {
                                                    "product_name": p_name,
                                                    "material": mat,
                                                    "taric": taric,
                                                    "cn_description": cn_desc,
                                                    "optional_translation": opt_trans,
                                                    "image": ""
                                                }
                                                total_imported += 1
                            except Exception:
                                pass
                                            
                    save_hs_database(db_current)
                    st.success(f"✅ Pomyślnie zaimportowano i zaktualizowano **{total_imported}** wzorców z plików do bazy!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Błąd przetwarzania plików: {str(e)}")

    st.markdown("---")
    search_query = st.text_input("🔍 Szukaj w bazie (wpisz nazwę, skład np. IRON/PU/WOOD, lub kod CN):", "").strip().lower()

    st.markdown("---")
    st.subheader("📋 Wyniki i Lista Wzorców")
    
    if hs_db:
        filtered_items = []
        for key, val in hs_db.items():
            prod = str(val.get("product_name", "")).lower()
            mat = str(val.get("material", "")).lower()
            taric = str(val.get("taric", "")).lower()
            cn_desc = str(val.get("cn_description", "")).lower()
            opt_trans = str(val.get("optional_translation", "")).lower()
            
            if not search_query or (search_query in prod or search_query in mat or search_query in taric or search_query in cn_desc or search_query in opt_trans):
                filtered_items.append((key, val))

        if filtered_items:
            st.write(f"Znaleziono pasujących wzorców: **{len(filtered_items)}**")
            for key, val in filtered_items:
                col_img, col_txt, col_del = st.columns([1, 4, 1])
                with col_img:
                    img_file = val.get("image", "")
                    if img_file and os.path.exists(os.path.join(IMG_DB_DIR, img_file)):
                        st.image(os.path.join(IMG_DB_DIR, img_file), width=100)
                    else:
                        st.markdown("*(Brak zdjęcia)*")
                with col_txt:
                    st.markdown(f"**Nazwa Produktu:** {val.get('product_name', '')}")
                    st.markdown(f"**Skład Materiałowy:** `{val.get('material', 'N/D')}`")
                    st.markdown(f"**Google Translate:** {val.get('optional_translation', 'Brak')}")
                    st.markdown(f"**Kod TARIC/CN:** `{val.get('taric', '')}`")
                    st.markdown(f"**Oficjalny Opis CN:** {val.get('cn_description', 'N/D')}")
                with col_del:
                    if st.button("Usuń", key=f"del_{key}"):
                        del hs_db[key]
                        save_hs_database(hs_db)
                        st.rerun()
                st.markdown("---")
        else:
            st.warning("Brak wyników spełniających kryteria wyszukiwania.")
    else:
        st.write("Baza jest obecnie pusta.")

# ==============================================================================
# MODUŁ 2: INTRASTAT
# ==============================================================================
elif app_mode == "📦 Dedykowany Generator INTRASTAT (Huzar)":
    st.title("📦 Moduł INTRASTAT — Generator Faktur XML dla Huzar WinSAD")
    if not st.session_state.current_company:
        st.warning("⚠️ Najpierw dodaj i wybierz firmę w panelu bocznym!")
    else:
        st.info(f"📂 **Aktywna Firma w module INTRASTAT:** `{st.session_state.current_company}`")

    st.caption("Moduł automatycznie sumuje sztuki, masy i wartości dla tożsamych kodów CN w ramach faktury dla wybranej firmy.")

    uploaded_intra_docs = st.file_uploader(
        "Wgraj paczkę ZIP lub pliki handlowe (PDF / Excel / Skany)",
        type=["zip", "pdf", "xlsx", "xls", "png", "jpg"],
        accept_multiple_files=True,
        key="intra_files"
    )

    if st.button("⚡ Przetwarzaj Faktury i Generuj XML dla Huzara", type="primary", use_container_width=True):
        if not uploaded_intra_docs:
            st.warning("⚠️ Wgraj przynajmniej jeden dokument lub plik ZIP!")
        elif not api_key:
            st.error("Wpisz klucz API Gemini w panelu bocznym.")
        elif not st.session_state.current_company:
            st.error("Wybierz najpierw firmę w panelu bocznym.")
        else:
            try:
                processed_intra_docs = []
                for f in uploaded_intra_docs:
                    f_bytes = f.getvalue()
                    if not f_bytes: continue
                    if f.name.lower().endswith(".zip"):
                        with zipfile.ZipFile(BytesIO(f_bytes)) as z:
                            for filename in z.namelist():
                                if filename.endswith('/') or '__MACOSX' in filename or filename.startswith('.'):
                                    continue
                                file_data = z.read(filename)
                                base_name = os.path.basename(filename)
                                if not base_name: continue
                                class ZipFileWrapper:
                                    def __init__(self, name, data):
                                        self.name = name
                                        self._data = data
                                    def getvalue(self):
                                        return self._data
                                processed_intra_docs.append(ZipFileWrapper(base_name, file_data))
                    else:
                        processed_intra_docs.append(f)

                client = genai.Client(api_key=api_key)
                prompt_intra = (
                    f"Jesteś precyzyjnym systemem OCR do faktur handlowych dla Intrastat dla firmy: {st.session_state.current_company}.\n"
                    "Przeanalizuj poniższe dane ze wszystkich wgranych plików i zakładek Excel.\n"
                    "ZASADA BEZWZGLĘDNA: Odczytaj dokładnie numery faktur, kontrahentów, daty, NIP-y, wartości oraz kody CN.\n"
                    "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
                    "Sprzedawca_Nazwa;Sprzedawca_NIP;Sprzedawca_Kraj;Sprzedawca_Ulica;Sprzedawca_Kod;Sprzedawca_Miasto;Nr_Faktury;Data_Faktury;Nabywca_Nazwa;Nabywca_NIP;Nabywca_Kraj;Nabywca_Ulica;Nabywca_Kod;Nabywca_Miasto;Kod_CN;Opis_Towaru;Ilosc_Sztuk;Masa_Netto_KG;Wartosc_PLN"
                )

                contents = [prompt_intra]
                for f in processed_intra_docs:
                    f_bytes = f.getvalue()
                    ext = f.name.split(".")[-1].lower()
                    if ext in ["xlsx", "xls"]:
                        excel_text = process_excel_all_sheets(f_bytes)
                        contents.append(f"\n--- ZAWARTOŚĆ PLIKU EXCEL ({f.name} - wszystkie zakładki) ---\n" + excel_text + "\n")
                    elif ext == "pdf":
                        try:
                            contents.append(types.Part.from_bytes(data=f_bytes, mime_type="application/pdf"))
                        except Exception:
                            pass
                    elif ext in ["jpg", "jpeg"]:
                        contents.append(types.Part.from_bytes(data=f_bytes, mime_type="image/jpeg"))
                    elif ext == "png":
                        contents.append(types.Part.from_bytes(data=f_bytes, mime_type="application/png"))

                with st.spinner(f"Odczytywanie dokumentów dla firmy {st.session_state.current_company} i przygotowanie struktury TFakturyHS..."):
                    res_intra = safe_generate_content(client, selected_model, contents)
                    df_processed = process_intrastat_dataframe(res_intra.text)
                    st.session_state.df_intra_result = df_processed
                    st.success(f"✅ Pomyślnie przetworzono dokumenty (liczba faktur: {len(df_processed)})!")

            except Exception as e:
                st.error(f"Błąd przetwarzania: {str(e)}")

    if "df_intra_result" in st.session_state:
        st.markdown("---")
        st.markdown(f"### 📋 Podgląd Zagregowanych Pozycji Intrastat dla Firmy: {st.session_state.current_company}")
        df_edited_intra = st.data_editor(
            st.session_state.df_intra_result,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic"
        )
        xml_huzar_bytes = generate_huzarfaktury_xml(df_edited_intra)
        st.download_button(
            label="📥 Pobierz Poprawiony Plik XML (TFakturyHS z WDT) pod Huzar WinSAD",
            data=xml_huzar_bytes,
            file_name=f"FakturyHS_Intrastat_{st.session_state.current_company}_PLN.xml",
            mime="application/xml",
            use_container_width=True
        )

# ==============================================================================
# MODUŁ 1: FIRMY I KONTENERY
# ==============================================================================
elif app_mode == "🚢 Odprawy i Taryfikacja Kontenerów":
    if not st.session_state.current_company:
        st.title("Genius AI BOT — Dodaj i Wybierz Firmę")
        st.warning("⚠️ Najpierw dodaj firmę w panelu bocznym po lewej stronie, aby móc zarządzać jej kontenerami.")
    else:
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**📂 Aktywna Firma:** `{st.session_state.current_company}`")
        
        new_no = st.sidebar.text_input("Numer Kontenera dla tej firmy", placeholder="np. CNEU4699420").upper().strip()
        if st.sidebar.button("+ Dodaj Kontener do Firmy", use_container_width=True):
            if new_no:
                if new_no not in st.session_state.company_data[st.session_state.current_company]:
                    st.session_state.company_data[st.session_state.current_company][new_no] = {
                        "docs": [], "out1": "", "out2": "", "out3": "", "calc_audit": "", "hs_approved": [], "cbam_data": "", "cbam_audit_result": ""
                    }
                    save_container_data(st.session_state.current_company, new_no, st.session_state.company_data[st.session_state.current_company][new_no])
                st.session_state.current_container = new_no
                st.sidebar.success(f"Aktywowano kontener: {new_no}")
                st.rerun()

        containers_dict = st.session_state.company_data[st.session_state.current_company]
        if containers_dict:
            cont_list = list(containers_dict.keys())
            curr_cont_idx = cont_list.index(st.session_state.current_container) if st.session_state.current_container in cont_list else 0
            selected_cont = st.sidebar.selectbox("📦 Wybierz Kontener", options=cont_list, index=curr_cont_idx)
            st.session_state.current_container = selected_cont

            if st.sidebar.button("❌ Usuń bieżący kontener", type="secondary", use_container_width=True):
                delete_container_dir(st.session_state.current_company, st.session_state.current_container)
                del st.session_state.company_data[st.session_state.current_company][st.session_state.current_container]
                remaining = list(st.session_state.company_data[st.session_state.current_company].keys())
                st.session_state.current_container = remaining[0] if remaining else None
                st.rerun()

    st.sidebar.markdown("---")
    hs_db = load_hs_database()
    st.sidebar.markdown(f"**🗄️ Baza Wizualna HS:** `{len(hs_db)} wzorców`")

    if not st.session_state.current_company or not st.session_state.current_container:
        st.title("Genius AI BOT — Gotowy do Pracy")
        st.info("Wybierz firmę oraz kontener w panelu bocznym.")
    else:
        cur_comp = st.session_state.current_company
        cur_no = st.session_state.current_container
        proj = st.session_state.company_data[cur_comp][cur_no]

        st.title(f"Genius AI BOT | Firma: `{cur_comp}` ➔ Kontener: `{cur_no}`")

        uploaded_files = st.file_uploader(
            "1. Dokumenty Ładunkowe (Wgraj plik ZIP lub pojedyncze CI, PL, BL, Odprawa Chińska / 报关单, Excel)",
            type=["zip", "pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
            accept_multiple_files=True
        )

        if uploaded_files:
            saved_docs = save_uploaded_files(cur_comp, cur_no, uploaded_files)
            proj["docs"] = saved_docs
            st.success(f"Zapisano i załączono dokumenty: łączna liczba plików to {len(proj['docs'])}")
        elif proj.get("docs"):
            st.info(f"📂 Wczytano zapisane dokumenty z dysku ({len(proj['docs'])} szt.): " + ", ".join([d.name for d in proj["docs"]]))

        def call_ai(prompt, msg="Przetwarzanie dokumentów przez Genius AI BOT..."):
            if not api_key: st.error("Brak klucza API!"); return None
            if not proj.get("docs"): st.error("Brak załączonych plików dla tego kontenera!"); return None
            try:
                client = genai.Client(api_key=api_key)
                contents = [prompt]
                for f in proj["docs"]:
                    f_bytes = f.getvalue()
                    if not f_bytes: continue
                    if f.type == "spreadsheet":
                        excel_text = process_excel_all_sheets(f_bytes)
                        contents.append(f"\n--- ZAWARTOŚĆ PLIKU EXCEL ({f.name} - wszystkie zakładki) ---\n" + excel_text + "\n")
                    elif f.type == "application/pdf":
                        try:
                            contents.append(types.Part.from_bytes(data=f_bytes, mime_type="application/pdf"))
                        except Exception:
                            pass
                    elif f.type in ["image/jpeg", "application/png"]:
                        contents.append(types.Part.from_bytes(data=f_bytes, mime_type=f.type))
                with st.spinner(msg):
                    res = safe_generate_content(client, selected_model, contents)
                    return res.text
            except Exception as e:
                st.error(f"Błąd połączenia: {str(e)}")
                return None

        PROMPT_ETAP1 = (
            f"Jesteś bezwzględnym i niezwykle skrupulatnym starszym audytorem celnym w Genius Logistics dla firmy: {cur_comp}.\n"
            "Przeanalizuj poniższe dane ze wszystkich dokumentów oraz wszystkich zakładek w plikach Excel.\n"
            "Twoim zadaniem jest przeprowadzenie rygorystycznej KONTROLI FORMALNEJ I KRZYŻOWEJ (Cross-Check).\n\n"
            "BEZWZGLĘDNY WYMÓG ROZDZIELNEJ KONTROLI ILOŚCI I KARTONÓW:\n"
            "1. SZTUKI (Quantity / pcs): Porównaj pozycję po pozycji liczbę sztuk na Fakturze z liczbą sztuk na Liście Pakującej oraz Odprawie Chińskiej.\n"
            "2. KARTONY / OPAKOWANIA (CTNS / Cartons / Packages): Przeprowadź ODRĘBNY, niezależny audyt liczby kartonów.\n"
            "3. Jeśli brakuje spójności, stwórz czytelną tabelę rozbieżności z podziałem na: [Nazwa Towaru | Sztuki na Fakturze | Sztuki na PL | Kartony na Fakturze | Kartony na PL | Wykryta Różnica].\n\n"
            "Użyj przejrzystego formatowania Markdown z nagłówkami i ikonami:\n"
            "### 📄 1. Identyfikacja Dokumentów i Stron\n"
            "### 🇨🇳 2. Weryfikacja i Porównanie z Odprawą Chińską\n"
            "### 🔢 3. KONTROLA ILOŚCI SZTUK (CI vs PL / Odprawa)\n"
            "### 📦 4. KONTROLA LICZBY KARTONÓW (CI vs PL / Odprawa)\n"
            "### ⚓ 5. Warunki Dostawy i Logistyka\n"
            "### ✍️ 6. Kontrola Podpisów, Pieczęci i Unikalnych Identyfikatorów\n"
            "### 🔍 7. Podsumowanie, Wykryte Błędy Techniczne i Wnioski Celne"
        )

        if st.button("🚀 Wykonaj Pełną Analizę (Etapy 1 - 3)", type="primary", use_container_width=True):
            if not proj.get("docs"):
                st.warning("Najpierw załącz dokumenty ładunkowe!")
            else:
                res1 = call_ai(PROMPT_ETAP1, "Krok 1/3: Rygorystyczny audyt sztuk i kartonów (Cross-Check)...")
                if res1: proj["out1"] = res1

                p2 = (
                    "Jesteś precyzyjnym skanerem OCR. Przeanalizuj poniższe dane z dokumentów oraz ze wszystkich zakładek Excel.\n"
                    "Odczytaj KAŻDĄ pozycję faktury/PL/Odprawy Chińskiej/tabeli z osobna.\n"
                    "ZASADA BEZWZGLĘDNA: Oddziel nazwę produktu od składu materiałowego (np. materiały takie jak: PU, IRON, WOOD, STEEL, PPE, PLASTIC itp.).\n"
                    "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
                    "POS;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
                )
                
                with st.spinner("Krok 2/3: Automatyczne odczytywanie i zbijanie pozycji w tle..."):
                    client_obj = genai.Client(api_key=api_key)
                    raw_ocr_text = call_ai(p2, "Krok 2/3: Odczytywanie OCR z dokumentów...")
                    if raw_ocr_text:
                        res2 = call_ai_chunked_stage2(client_obj, selected_model, p2, raw_ocr_text)
                        proj["out2"] = res2

                if proj.get("out2"):
                    df_grouped_temp = process_stage_2_dataframe(proj["out2"])
                    
                    with st.spinner("Krok 3/3: Automatyczna taryfikacja zbitych pozycji..."):
                        res3 = call_ai_chunked_stage3(client_obj, selected_model, df_grouped_temp)
                        
                    if res3:
                        try:
                            df_temp_t3 = parse_stage_3_csv(res3)
                            translations = []
                            for _, r_item in df_temp_t3.iterrows():
                                p_name = str(r_item.get("Nazwa Produktu", ""))
                                mat = str(r_item.get("Skład Materiałowy", ""))
                                combined = f"{p_name} ({mat})"
                                translations.append(translate_text_google(combined))
                            if "Opcjonalne Tłumaczenie" not in df_temp_t3.columns:
                                df_temp_t3.insert(4, "Opcjonalne Tłumaczenie", translations)
                            res3 = df_temp_t3.to_csv(index=False, sep=";")
                        except Exception:
                            pass
                        proj["out3"] = res3

                save_container_data(cur_comp, cur_no, proj)
                st.success("✅ Pełna analiza zakończona pomyślnie!")
                st.rerun()

        st.markdown("---")

        selected_tab = st.radio(
            "Wybierz Etap Analizy",
            ["📋 1. Kontrola Formalna i Odprawa Chińska", "🧩 2. Zbijanie Pozycji", "🏷️ 3. Taryfikacja & Weryfikacja Agenta"],
            horizontal=True
        )

        st.markdown("---")

        if selected_tab == "📋 1. Kontrola Formalna i Odprawa Chińska":
            st.subheader("📋 Audyt Formalny i Krzyżowa Kontrola z Odprawą Chińską")
            if st.button("Wykonaj Kontrolę Formalną", key="b1"):
                res = call_ai(PROMPT_ETAP1)
                if res: proj["out1"] = res; save_container_data(cur_comp, cur_no, proj); st.rerun()
            if proj.get("out1"):
                st.markdown("---")
                col_title, col_pdf = st.columns([3, 1])
                with col_title: st.success("✅ Wynik audytu gotowy")
                with col_pdf:
                    if FPDF_AVAILABLE:
                        pdf_bytes = generate_formal_pdf_report(cur_no, proj["out1"])
                        st.download_button("📄 Pobierz Raport PDF (.pdf)", data=pdf_bytes, file_name=f"Raport_Formalny_{cur_comp}_{cur_no}.pdf", mime="application/pdf", use_container_width=True)
                st.markdown(proj["out1"])

        elif selected_tab == "🧩 2. Zbijanie Pozycji":
            st.subheader("🧩 Agregacja Pozycji (Rozdzielenie Nazwy i Materiału)")
            if st.button("Wykonaj Zbijanie Pozycji", key="b2"):
                p2 = (
                    "Jesteś precyzyjnym skanerem OCR. Przeanalizuj poniższe dane z dokumentów i ze wszystkich zakładek Excel.\n"
                    "Odczytaj KAŻDĄ pozycję faktury/PL z osobna.\n"
                    "Oddziel nazwę produktu od składu materiałowego (np. PU, IRON, WOOD, STEEL, PPE).\n"
                    "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
                    "POS;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
                )
                with st.spinner("Automatyczne zbijanie pozycji..."):
                    client_obj = genai.Client(api_key=api_key)
                    raw_ocr_text = call_ai(p2)
                    if raw_ocr_text:
                        res = call_ai_chunked_stage2(client_obj, selected_model, p2, raw_ocr_text)
                        if res: proj["out2"] = res; save_container_data(cur_comp, cur_no, proj); st.rerun()
            
            if proj.get("out2"):
                try:
                    grouped = process_stage_2_dataframe(proj["out2"])
                    
                    total_ctns = grouped["CTNS"].sum()
                    total_qty = grouped["Quantity (pcs.)"].sum()
                    total_nw = grouped["N.W KGS"].sum()
                    total_gw = grouped["G.W KGS"].sum()
                    total_amt = grouped["Amount (EUR)"].sum()

                    col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)
                    with col_kpi1: st.metric("Kartony", f"{total_ctns:,.0f}")
                    with col_kpi2: st.metric("Sztuki", f"{total_qty:,.0f}")
                    with col_kpi3: st.metric("Masa Netto", f"{total_nw:,.1f} kg")
                    with col_kpi4: st.metric("Masa Brutto", f"{total_gw:,.1f} kg")
                    with col_kpi5: st.metric("Wartość", f"{total_amt:,.2f}")

                    st.dataframe(grouped, use_container_width=True, hide_index=True)
                    
                    st.markdown("---")
                    if st.button("🔍 Niezależny audyt rozbieżności sztuk i kartonów (CI vs PL)", key="btn_audit_calc"):
                        table_csv_preview = grouped.to_csv(index=False, sep=";")
                        audit_prompt = (
                            "Jesteś rygorystycznym audytorem celno-finansowym w Genius Logistics.\n"
                            "Oto zagregowana tabela pozycji towarowych po zbijaniu:\n"
                            f"{table_csv_preview}\n\n"
                            "Przeanalizuj oryginalne dokumenty i wykonaj SZCZEGÓŁOWY AUDYT ROZBIEŻNOŚCI:\n"
                            "1. Porównaj ODRĘBNIE liczbę sztuk oraz liczbę kartonów dla każdej pozycji między Fakturą a Packing Listą.\n"
                            "2. Jeśli występują różnice, wypisz je precyzyjnie w punktach.\n"
                            "3. Sprawdź ogólne sumy."
                        )
                        audit_res = call_ai(audit_prompt, "Audytor niezależnie weryfikuje rozbieżności sztuk i kartonów...")
                        if audit_res:
                            proj["calc_audit"] = audit_res
                            save_container_data(cur_comp, cur_no, proj)
                            st.rerun()

                    if proj.get("calc_audit"):
                        st.info("📌 **Wynik Audytu Rozbieżności Sztuk i Kartonów:**")
                        st.markdown(proj["calc_audit"])
                        st.markdown("---")

                    df_excel = grouped.copy()
                    for col in ["N.W KGS", "G.W KGS", "Amount (EUR)"]:
                        df_excel[col] = df_excel[col].apply(lambda x: f"{x:.2f}".replace(".", ","))
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_excel.to_excel(writer, index=False, sheet_name='Zbicie Pozycji')
                    st.download_button("📊 Pobierz zweryfikowany plik Excel (.xlsx)", data=output.getvalue(), file_name=f"Genius_AI_Zbicie_{cur_comp}_{cur_no}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                except Exception as e:
                    st.error(f"Błąd przetwarzania matematycznego: {str(e)}")

        elif selected_tab == "🏷️ 3. Taryfikacja & Weryfikacja Agenta":
            st.subheader("🏷️ Etap 3: Taryfikacja (Nazwa + Skład Materiału + Google Translate)")
            if not proj.get("out2"):
                st.warning("⚠️ Najpierw wykonaj Etap 2 (Zbijanie Pozycji)!")
            else:
                if st.button("Wykonaj Taryfikację Zbieganych Pozycji", key="b3"):
                    try:
                        df_stage2 = process_stage_2_dataframe(proj["out2"])
                        with st.spinner("Automatyczna taryfikacja paczkowa w tle..."):
                            client_obj = genai.Client(api_key=api_key)
                            res = call_ai_chunked_stage3(client_obj, selected_model, df_stage2)
                        if res:
                            df_temp_t3 = parse_stage_3_csv(res)
                            translations = []
                            for _, r_item in df_temp_t3.iterrows():
                                p_name = str(r_item.get("Nazwa Produktu", ""))
                                mat = str(r_item.get("Skład Materiałowy", ""))
                                combined = f"{p_name} ({mat})"
                                translations.append(translate_text_google(combined))
                            if "Opcjonalne Tłumaczenie" not in df_temp_t3.columns:
                                df_temp_t3.insert(4, "Opcjonalne Tłumaczenie", translations)
                            proj["out3"] = df_temp_t3.to_csv(index=False, sep=";")
                            save_container_data(cur_comp, cur_no, proj)
                            st.rerun()
                    except Exception as e:
                        st.error(f"Błąd: {str(e)}")

                if proj.get("out3"):
                    try:
                        df_t3 = parse_stage_3_csv(proj["out3"])
                        current_db = load_hs_database()
                        db_matched, final_codes, cn_descriptions, opt_translations, statuses, db_images = [], [], [], [], [], []
                        
                        for _, row in df_t3.iterrows():
                            p_name = str(row.get("Nazwa Produktu", "")).strip()
                            mat = str(row.get("Skład Materiałowy", "")).strip()
                            proposed_code = str(row.get("TARIC_PROPOSED", row.get("CN_HS_CODE", ""))).strip()
                            proposed_cn_desc = str(row.get("Oficjalny Opis CN", row.get("Reasoning", ""))).strip()
                            
                            if "Opcjonalne Tłumaczenie" in df_t3.columns and pd.notna(row.get("Opcjonalne Tłumaczenie")):
                                proposed_opt_trans = str(row.get("Opcjonalne Tłumaczenie", "")).strip()
                            else:
                                proposed_opt_trans = translate_text_google(f"{p_name} ({mat})")
                            
                            matched_in_db = False
                            for db_k, db_v in current_db.items():
                                db_prod = str(db_v.get("product_name", "")).strip().lower()
                                db_mat = str(db_v.get("material", "")).strip().lower()
                                db_taric = str(db_v.get("taric", "")).strip().lower()
                                
                                if db_prod == p_name.lower() and db_mat == mat.lower() and db_taric == proposed_code.lower():
                                    db_matched.append(True)
                                    final_codes.append(db_v.get("taric", proposed_code))
                                    cn_descriptions.append(db_v.get("cn_description", proposed_cn_desc))
                                    opt_translations.append(db_v.get("optional_translation", proposed_opt_trans))
                                    statuses.append("🟢 BAZA (Auto-Zaakceptowano)")
                                    db_images.append(db_v.get("image", ""))
                                    matched_in_db = True
                                    break
                            
                            if not matched_in_db:
                                db_matched.append(False)
                                final_codes.append(proposed_code)
                                cn_descriptions.append(proposed_cn_desc)
                                opt_translations.append(proposed_opt_trans)
                                statuses.append("🟡 Do Weryfikacji AI")
                                db_images.append("")

                        df_t3["Status Bazy"] = statuses
                        df_t3["Opcjonalne Tłumaczenie"] = opt_translations
                        df_t3["Oficjalny Opis CN"] = cn_descriptions
                        df_t3["Zdjęcie wzorca"] = db_images

                        st.markdown("### 🤖 3A. Propozycje AI i Dopasowania z Wizualnej Bazy")
                        st.dataframe(df_t3, use_container_width=True, hide_index=True)
                        st.markdown("---")
                        st.markdown("### 👨‍💼 3B. Weryfikacja & Akceptacja Agenta Celnego")
                        st.info("💡 **Wskazówka:** System sprawdza 3 parametry zgodności (`Nazwa + Skład + Kod CN`) z Twoją Bazą Wizualną. Możesz edytować dowolne pole w tabeli poniżej.")

                        if "df_editor" not in proj or not proj["hs_approved"]:
                            df_editor_init = df_t3.copy()
                            df_editor_init["Zaakceptowano"] = db_matched
                            df_editor_init["Ostateczny Kod TARIC"] = final_codes
                            df_editor_init["Skład Materiałowy"] = [str(r.get("Skład Materiałowy", "")) for _, r in df_t3.iterrows()]
                            df_editor_init["Opcjonalne Tłumaczenie"] = opt_translations
                            df_editor_init["Oficjalny Opis CN"] = cn_descriptions
                            df_editor_init["Uwagi Agenta"] = ["Potwierdzono z Bazy (3 parametry)" if m else "Do weryfikacji" for m in db_matched]
                        else:
                            df_editor_init = pd.DataFrame(proj["hs_approved"])

                        edited_df = st.data_editor(df_editor_init, use_container_width=True, hide_index=True, num_rows="dynamic", key=f"editor_{cur_no}")

                        st.markdown("---")
                        upload_db_img = st.file_uploader("📷 Wgraj zdjęcie referencyjne dla tych pozycji do bazy (opcjonalnie)", type=["jpg", "jpeg", "png"], key=f"img_up_{cur_no}")

                        if st.button("💾 Zatwierdź Kody HS dla Urzędu Celnego i Zapisz do Bazy", type="primary"):
                            records = edited_df.to_dict(orient="records")
                            proj["hs_approved"] = records
                            save_container_data(cur_comp, cur_no, proj)
                            added = update_hs_database_from_records(records, upload_db_img)
                            st.success(f"✅ Zatwierdzono! Dodano/zaktualizowano {added} wzorców w Wizualnej Bazie (wg 3 parametrów).")
                            st.rerun()

                        if proj.get("hs_approved"):
                            st.markdown("---")
                            st.success("🔒 **Dokumentacja gotowa do PUESC / Huzar**")
                            df_approved = pd.DataFrame(proj["hs_approved"])
                            out_final_excel = BytesIO()
                            with pd.ExcelWriter(out_final_excel, engine='openpyxl') as writer:
                                df_approved.to_excel(writer, index=False, sheet_name='HS_CODE_APPROVED')
                            st.download_button("🏛️ Pobierz Zgodę Celną Excel (.xlsx)", data=out_final_excel.getvalue(), file_name=f"HS_APPROVED_{cur_comp}_{cur_no}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                    except Exception as e:
                        st.error(f"Błąd parsowania taryfikacji: {str(e)}")
