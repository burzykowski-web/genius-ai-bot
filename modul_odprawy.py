# -*- coding: utf-8 -*-
"""
Moduł 1: Odprawy i Taryfikacja Kontenerów oraz Raporty Formalne
"""
import os
import re
import pandas as pd
from io import BytesIO

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

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
    try:
        pdf_output = pdf.output(dest='S')
        if isinstance(pdf_output, str):
            return pdf_output.encode('latin-1', 'replace')
        return pdf_output
    except Exception:
        return bytes(pdf.output())

def process_stage_2_dataframe(out2_text):
    from io import StringIO
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
    from io import StringIO
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
