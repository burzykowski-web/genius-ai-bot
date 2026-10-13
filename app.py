# -*- coding: utf-8 -*-
import os
import json
import time
import zipfile
from io import BytesIO
from datetime import datetime
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# Importy modułów
from modul_odprawy import generate_formal_pdf_report, process_stage_2_dataframe, parse_stage_3_csv
from modul_intrastat import process_intrastat_dataframe, generate_huzarfaktury_xml
from modul_baza_hs import load_hs_database, save_hs_database, update_hs_database_from_records
from modul_cbam import generate_cbam_pdf_report

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

try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = ""

if not api_key:
    st.error("⚠️ Brak klucza API w Secrets (GEMINI_API_KEY).")
    st.stop()

selected_model = "gemini-3.6-flash"

DATA_DIR = "projects_data"
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
        elif ext in ["xlsx", "xls", "xlsm", "csv"]: self.type = "spreadsheet"
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
    try:
        for company_name in os.listdir(DATA_DIR):
            comp_dir = os.path.join(DATA_DIR, company_name)
            if os.path.isdir(comp_dir) and company_name != "db_images":
                data_struct[company_name] = {}
                for container_no in os.listdir(comp_dir):
                    cont_dir = os.path.join(comp_dir, container_no)
                    if os.path.isdir(cont_dir):
                        json_path = os.path.join(cont_dir, "data.json")
                        c_data = {"out1": "", "out2": "", "out3": "", "calc_audit": "", "docs": [], "hs_approved": [], "cross_check_df": []}
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
    except Exception:
        pass
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
        "cross_check_sku_result": data.get("cross_check_sku_result", ""),
        "cross_check_df": data.get("cross_check_df", [])
    }
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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
        try:
            shutil.rmtree(cont_dir)
        except Exception:
            pass

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

def process_excel_all_sheets_to_csv_rows(f_bytes, filename="plik.xls"):
    all_rows = []
    try:
        ext = filename.split(".")[-1].lower()
        if ext == "csv":
            for enc in ['utf-8', 'latin-1', 'cp1250']:
                try:
                    df_csv = pd.read_csv(BytesIO(f_bytes), header=None, encoding=enc, on_bad_lines='skip')
                    for _, row in df_csv.iterrows():
                        row_str = " | ".join([str(val) for val in row.values if pd.notna(val) and str(val).strip() != ""])
                        if row_str:
                            all_rows.append(row_str)
                    if all_rows:
                        return all_rows
                except Exception:
                    continue

        xls = pd.ExcelFile(BytesIO(f_bytes))
        for sheet_name in xls.sheet_names:
            try:
                df_sheet = xls.parse(sheet_name, header=None)
                df_sheet = df_sheet.dropna(how='all')
                for _, row in df_sheet.iterrows():
                    row_str = " | ".join([str(val) for val in row.values if pd.notna(val) and str(val).strip() != ""])
                    if row_str:
                        all_rows.append(f"[{sheet_name}] {row_str}")
            except Exception:
                continue
    except Exception:
        pass

    if not all_rows:
        try:
            raw_text = f_bytes.decode('latin-1', errors='ignore')
            for line in raw_text.split('\n'):
                clean_l = "".join([c for c in line if c.isalnum() or c in " ;,-_/()."])
                if len(clean_l.strip()) > 3:
                    all_rows.append(clean_l.strip())
        except Exception:
            pass

    return all_rows if all_rows else [f"Dane z pliku {filename}"]

def call_ai_chunked_stage2_massive(client, model_name, base_prompt, rows_list):
    chunk_size = 150
    chunks = [rows_list[i:i + chunk_size] for i in range(0, len(rows_list), chunk_size)]
    
    combined_csv_rows = []
    header_str = "POS;Catalog_No;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
    combined_csv_rows.append(header_str)
    
    for idx, chunk in enumerate(chunks):
        chunk_text = "\n".join(chunk)
        chunk_prompt = (
            f"{base_prompt}\n"
            f"(Paczka {idx+1} z {len(chunks)}. Zwróć wynik jako format CSV ze średnikami bez nagłówka)."
        )
        try:
            res = safe_generate_content(client, model_name, [chunk_prompt, chunk_text])
            clean_res = res.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
            for r_line in clean_res.split('\n'):
                if r_line.strip() and not r_line.upper().startswith("POS;"):
                    combined_csv_rows.append(r_line)
        except Exception:
            pass
            
    return "\n".join(combined_csv_rows)

def call_ai_chunked_stage3(client, model_name, summary_df):
    records = summary_df.to_dict(orient="records")
    chunk_size = 100
    chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]
    
    all_t3_rows = []
    header_str = "pos;Invoice Positions;Nazwa Produktu;Skład Materiałowy;Opcjonalne Tłumaczenie;TARIC_PROPOSED;CN_HS_CODE;Oficjalny Opis CN;Reasoning"
    all_t3_rows.append(header_str)
    
    for idx, chunk in enumerate(chunks):
        sub_df = pd.DataFrame(chunk)
        chunk_summary = sub_df[["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE"]].to_csv(index=False, sep=";")
        p3_prompt = (
            f"Jesteś agentem celnym. Wycinek pozycji (paczka {idx+1} z {len(chunks)}):\n"
            f"{chunk_summary}\n\n"
            f"Zwróć wynik jako czysty CSV ze średnikami (;) bez nagłówka:\n"
        )
        try:
            res = safe_generate_content(client, model_name, [p3_prompt])
            clean_res = res.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
            for r_line in clean_res.split('\n'):
                if r_line.strip() and not r_line.upper().startswith("POS;"):
                    all_t3_rows.append(r_line)
        except Exception:
            pass
    return "\n".join(all_t3_rows)

# --- INICJALIZACJA STANU Z DYSKU ---
if "company_data" not in st.session_state:
    st.session_state.company_data = load_companies_and_containers()

disk_data = load_companies_and_containers()
if disk_data and not st.session_state.company_data:
    st.session_state.company_data = disk_data
elif disk_data and st.session_state.company_data:
    for comp, conts in disk_data.items():
        if comp not in st.session_state.company_data:
            st.session_state.company_data[comp] = conts
        else:
            for cont, c_val in conts.items():
                if cont not in st.session_state.company_data[comp]:
                    st.session_state.company_data[comp][cont] = c_val

if "current_company" not in st.session_state:
    if st.session_state.company_data:
        st.session_state.current_company = list(st.session_state.company_data.keys())[0]
    else:
        st.session_state.current_company = None

if "current_container" not in st.session_state:
    if st.session_state.current_company and st.session_state.current_company in st.session_state.company_data:
        conts = list(st.session_state.company_data[st.session_state.current_company].keys())
        st.session_state.current_container = conts[0] if conts else None
    else:
        st.session_state.current_container = None

st.sidebar.markdown("### 🚢 Genius AI BOT")
st.sidebar.markdown("Enterprise Logistics Platform")
st.sidebar.markdown("---")

st.sidebar.markdown("### 🏢 Globalny Wybór Firmy")
new_comp = st.sidebar.text_input("Nazwa Nowej Firmy", placeholder="np. Firma XYZ").strip()
if st.sidebar.button("+ Dodaj Firmę", use_container_width=True):
    if new_comp:
        if new_comp not in st.session_state.company_data:
            st.session_state.company_data[new_comp] = {}
        st.session_state.current_company = new_comp
        st.session_state.current_container = None
        save_container_data(new_comp, "DUMMY", {})
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

hs_db_sidebar = load_hs_database()
st.sidebar.markdown(f"**🗄️ Baza Wizualna HS:** `{len(hs_db_sidebar)} wzorców`")

if app_mode == "🗄️ Wizualna Baza Kodów HS":
    st.title("🗄️ Wizualna Baza Wiedzy (Nazwa + Skład + Kod CN)")
    st.caption("Przeglądaj, wyszukuj, pobieraj backup i zarządzaj wzorcami towarowymi zapamiętanymi przez system.")

    hs_db = load_hs_database()
    st.info(f"Aktualna liczba wzorców w bazie: **{len(hs_db)}**")

    col_exp, col_imp = st.columns(2)
    with col_exp:
        from modul_baza_hs import export_hs_database_json, import_hs_database_from_json
        json_bytes = export_hs_database_json()
        st.download_button(
            "📥 Pobierz kopię bazy na komputer (Backup JSON)",
            data=json_bytes,
            file_name=f"hs_database_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    with col_imp:
        uploaded_backup = st.file_uploader("📤 Wgraj plik bazy (Przywróć z kopii)", type=["json"], key="import_db_json")
        if uploaded_backup is not None:
            if st.button("Przywróć bazę z wgranego pliku", use_container_width=True):
                success, res_msg = import_hs_database_from_json(uploaded_backup.getvalue())
                if success:
                    st.success(f"✅ Pomyślnie przywrócono bazę! Liczba wzorców: {res_msg}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"❌ Błąd importu: {res_msg}")

    st.markdown("---")
    search_query = st.text_input("🔍 Szukaj w bazie (wpisz nazwę, skład lub kod CN):", "").strip().lower()
    st.markdown("---")
    
    if hs_db:
        filtered_items = []
        for key, val in hs_db.items():
            prod = str(val.get("product_name", "")).lower()
            mat = str(val.get("material", "")).lower()
            taric = str(val.get("taric", "")).lower()
            cn_desc = str(val.get("cn_description", "")).lower()
            
            if not search_query or (search_query in prod or search_query in mat or search_query in taric or search_query in cn_desc):
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
                    st.markdown(f"**Kod TARIC/CN:** `{val.get('taric', '')}` | **Status:** `{val.get('status_celny', 'Zatwierdzony')}`")
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

elif app_mode == "🚢 Odprawy i Taryfikacja Kontenerów":
    if not st.session_state.current_company:
        st.title("Genius AI BOT — Dodaj i Wybierz Firmę")
        st.warning("⚠️ Najpierw dodaj firmę w panelu bocznym po lewej stronie.")
    else:
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**📂 Aktywna Firma:** `{st.session_state.current_company}`")
        
        new_no = st.sidebar.text_input("Numer Kontenera dla tej firmy", placeholder="np. CNEU4699420").upper().strip()
        if st.sidebar.button("+ Dodaj Kontener do Firmy", use_container_width=True):
            if new_no:
                if new_no not in st.session_state.company_data[st.session_state.current_company]:
                    st.session_state.company_data[st.session_state.current_company][new_no] = {
                        "docs": [], "out1": "", "out2": "", "out3": "", "calc_audit": "", "hs_approved": [], "cross_check_df": []
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

    if not st.session_state.current_company or not st.session_state.current_container:
        st.title("Genius AI BOT — Gotowy do Pracy")
        st.info("Wybierz firmę oraz kontener w panelu bocznym.")
    else:
        cur_comp = st.session_state.current_company
        cur_no = st.session_state.current_container
        proj = st.session_state.company_data[cur_comp][cur_no]

        st.title(f"Genius AI BOT | Firma: `{cur_comp}` ➔ Kontener: `{cur_no}`")

        if st.button("🧹 Wyczyść pamięć i pliki tego kontenera (Reset błędu)", type="secondary"):
            proj["docs"] = []
            proj["out2"] = ""
            delete_container_dir(cur_comp, cur_no)
            save_container_data(cur_comp, cur_no, proj)
            st.success("Zresetowano kontener. Wgraj teraz poprawny plik Excel od nowa.")
            st.rerun()

        uploaded_files = st.file_uploader(
            "1. Dokumenty Ładunkowe (Wgraj plik ZIP lub pojedyncze CI, PL, BL, Odprawa Chińska, Duży Excel - 2000+ pozycji)",
            type=["zip", "pdf", "xlsx", "xls", "xlsm", "csv", "png", "jpg", "jpeg"],
            accept_multiple_files=True
        )

        if uploaded_files:
            saved_docs = save_uploaded_files(cur_comp, cur_no, uploaded_files)
            proj["docs"] = saved_docs
            st.success(f"Zapisano i załączono dokumenty: {len(proj['docs'])} szt.")
        elif proj.get("docs"):
            st.info(f"📂 Wczytano zapisane dokumenty z dysku ({len(proj['docs'])} szt.)")

        def call_ai(prompt, msg="Przetwarzanie dokumentów przez Genius AI BOT..."):
            if not proj.get("docs"): st.error("Brak załączonych plików dla tego kontenera!"); return None
            try:
                client = genai.Client(api_key=api_key)
                contents = [prompt]
                for f in proj["docs"]:
                    f_bytes = f.getvalue()
                    if not f_bytes: continue
                    if f.type == "spreadsheet":
                        rows_data = process_excel_all_sheets_to_csv_rows(f_bytes, f.name)
                        contents.append(f"\n=== PLIK EXCEL ({f.name}) - Łącznie wierszy: {len(rows_data)} ===\n" + "\n".join(rows_data[:1500]))
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
            f"Jesteś bezwzględnym starszym audytorem celnym dla firmy: {cur_comp}.\n"
            "Przeprowadź rygorystyczną KONTROLĘ FORMALNĄ I KRZYŻOWĄ (Cross-Check).\n"
            "1. Sztuki (Quantity/pcs), 2. Kartony/Opakowania, 3. Tabela rozbieżności."
        )

        selected_tab = st.radio(
            "Wybierz Etap Analizy",
            [
                "📋 1. Kontrola Formalna i Odprawa Chińska", 
                "🧩 2. Zbijanie Pozycji (2000+ Excel)", 
                "🏷️ 3. Taryfikacja & Weryfikacja Agenta", 
                "🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej"
            ],
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
                        st.download_button("📄 Pobierz Raport PDF", data=pdf_bytes, file_name=f"Raport_Formalny_{cur_comp}_{cur_no}.pdf", mime="application/pdf", use_container_width=True)
                st.markdown(proj["out1"])

        elif selected_tab == "🧩 2. Zbijanie Pozycji (2000+ Excel)":
            st.subheader("🧩 Masowa Agregacja Pozycji (Wsparcie dla Plików 2000+ wierszy)")
            st.info("System wczyta każdą komórkę i zakładkę pliku Excel, rozdzieli nazwy od materiałów i zsumuje pozycje po Nazwie oraz Składzie.")

            if st.button("🚀 Uruchom Masowe Zbijanie Pozycji (Excel 2000+ wierszy)", key="b2_massive", type="primary", use_container_width=True):
                if not proj.get("docs"):
                    st.warning("⚠️ Najpierw załącz plik Excel lub dokumenty w górnym panelu!")
                else:
                    try:
                        client_obj = genai.Client(api_key=api_key)
                        all_excel_rows = []
                        
                        for f in proj["docs"]:
                            if f.type == "spreadsheet":
                                f_bytes = f.getvalue()
                                rows_extracted = process_excel_all_sheets_to_csv_rows(f_bytes, f.name)
                                all_excel_rows.extend(rows_extracted)
                        
                        if not all_excel_rows:
                            st.error("⚠️ Nie znaleziono załączonego pliku Excel w dokumentach kontenera! Wgraj plik w sekcji u góry.")
                        else:
                            st.write(f"📂 Wczytano łącznie **{len(all_excel_rows)}** wierszy tekstowych ze wszystkich zakładek Excel. Trwa masowe przetwarzanie AI...")
                            
                            p2 = (
                                "Jesteś precyzyjnym systemem celnym i OCR.\n"
                                "Przeanalizuj poniższe wiersze źródłowe wyciągnięte z pliku Excel.\n"
                                "Wyciągnij KAŻDĄ pozycję towarową, starannie rozdzielając Nazwę Produktu (przeznaczenie) od Składu Materiałowego oraz zsumuj ilości i masy.\n"
                                "Zwróć wynik jako czysty kod CSV ze średnikami (;) bez nagłówka w pierwszej linii:\n"
                                "POS;Catalog_No;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
                            )
                            
                            res_massive = call_ai_chunked_stage2_massive(client_obj, selected_model, p2, all_excel_rows)
                            proj["out2"] = res_massive
                            save_container_data(cur_comp, cur_no, proj)
                            st.success(f"✅ Masowe zbijanie 2000+ pozycji zakończone pomyślnie!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Błąd podczas masowego zbijania: {str(e)}")
            
            if proj.get("out2"):
                try:
                    grouped = process_stage_2_dataframe(proj["out2"])
                    if not grouped.empty:
                        col1, col2, col3, col4, col5 = st.columns(5)
                        col1.metric("Kartony", f"{grouped['CTNS'].sum():,.0f}")
                        col2.metric("Sztuki", f"{grouped['Quantity (pcs.)'].sum():,.0f}")
                        col3.metric("Masa Netto", f"{grouped['N.W KGS'].sum():,.1f} kg")
                        col4.metric("Masa Brutto", f"{grouped['G.W KGS'].sum():,.1f} kg")
                        col5.metric("Wartość", f"{grouped['Amount (EUR)'].sum():,.2f}")

                        st.markdown(f"**Liczba zsumowanych wierszy/pozycji po agregacji:** `{len(grouped)}`")
                        st.dataframe(grouped, use_container_width=True, hide_index=True)
                        
                        df_excel = grouped.copy()
                        for col in ["N.W KGS", "G.W KGS", "Amount (EUR)"]:
                            if col in df_excel.columns:
                                df_excel[col] = df_excel[col].apply(lambda x: f"{x:.2f}".replace(".", ","))
                        output = BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_excel.to_excel(writer, index=False, sheet_name='Zbicie Pozycji')
                        st.download_button("📊 Pobierz zweryfikowany plik Excel (.xlsx)", data=output.getvalue(), file_name=f"Genius_AI_Zbicie_{cur_comp}_{cur_no}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    else:
                        st.warning("⚠️ Otrzymano puste dane z analizy pliku Excel.")
                except Exception as e:
                    st.error(f"Błąd wyświetlania tabeli: {str(e)}")

        elif selected_tab == "🏷️ 3. Taryfikacja & Weryfikacja Agenta":
            st.subheader("🏷️ Etap 3: Taryfikacja (Pamięć po Nazwie i Składzie + AI)")
            if not proj.get("out2"):
                st.warning("⚠️ Najpierw wykonaj Etap 2 (Zbijanie Pozycji)!")
            else:
                if st.button("Wykonaj Taryfikację Zbieganych Pozycji", key="b3"):
                    try:
                        df_stage2 = process_stage_2_dataframe(proj["out2"])
                        with st.spinner("Masowa taryfikacja (sprawdzanie pamięci i AI)..."):
                            client_obj = genai.Client(api_key=api_key)
                            res = call_ai_chunked_stage3(client_obj, selected_model, df_stage2)
                        if res:
                            df_temp_t3 = parse_stage_3_csv(res)
                            translations = [translate_text_google(f"{r.get('Nazwa Produktu', '')} ({r.get('Skład Materiałowy', '')})") for _, r in df_temp_t3.iterrows()]
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
                        db_matched, final_codes, cn_descriptions, opt_translations, statuses = [], [], [], [], []
                        
                        for _, row in df_t3.iterrows():
                            p_name = str(row.get("Nazwa Produktu", "")).strip()
                            mat = str(row.get("Skład Materiałowy", "")).strip()
                            proposed_code = str(row.get("TARIC_PROPOSED", row.get("CN_HS_CODE", ""))).strip()
                            proposed_cn_desc = str(row.get("Oficjalny Opis CN", row.get("Reasoning", ""))).strip()
                            proposed_opt_trans = str(row.get("Opcjonalne Tłumaczenie", translate_text_google(f"{p_name} ({mat})"))).strip()
                            
                            matched_in_db = False
                            if p_name and mat:
                                db_key = f"{p_name.lower()}_{mat.lower()}"
                                if db_key in current_db:
                                    db_v = current_db[db_key]
                                    db_matched.append(True)
                                    final_codes.append(db_v.get("taric", proposed_code))
                                    cn_descriptions.append(db_v.get("cn_description", proposed_cn_desc))
                                    opt_translations.append(db_v.get("optional_translation", proposed_opt_trans))
                                    statuses.append("🟢 PAMIĘĆ BAZY (Auto)")
                                    matched_in_db = True

                            if not matched_in_db:
                                db_matched.append(False)
                                final_codes.append(proposed_code)
                                cn_descriptions.append(proposed_cn_desc)
                                opt_translations.append(proposed_opt_trans)
                                statuses.append("🟡 Do Weryfikacji AI")

                        df_t3["Status Bazy"] = statuses
                        df_t3["Opcjonalne Tłumaczenie"] = opt_translations
                        df_t3["Oficjalny Opis CN"] = cn_descriptions

                        if "df_editor" not in proj or not proj["hs_approved"]:
                            df_editor_init = df_t3.copy()
                            df_editor_init["Zaakceptowano"] = db_matched
                            df_editor_init["Ostateczny Kod TARIC"] = final_codes
                            df_editor_init["Status Celny"] = ["Potwierdzony Celnie (Odprawiony)" if m else "Do weryfikacji" for m in db_matched]
                        else:
                            df_editor_init = pd.DataFrame(proj["hs_approved"])

                        edited_df = st.data_editor(df_editor_init, use_container_width=True, hide_index=True, num_rows="dynamic", key=f"editor_{cur_no}")
                        upload_db_img = st.file_uploader("📷 Wgraj zdjęcie referencyjne", type=["jpg", "jpeg", "png"], key=f"img_up_{cur_no}")

                        if st.button("💾 Zatwierdź Kody HS i Zapisz do Bazy", type="primary"):
                            records = edited_df.to_dict(orient="records")
                            proj["hs_approved"] = records
                            save_container_data(cur_comp, cur_no, proj)
                            added = update_hs_database_from_records(records, upload_db_img, custom_status="Potwierdzony Celnie (Odprawiony)")
                            st.success(f"✅ Zatwierdono! Zaktualizowano {added} wzorców w Bazie.")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Błąd: {str(e)}")

        elif selected_tab == "🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej":
            st.subheader("🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa: Niemiecka Odprawa Celna vs Dokumenty Handlowe")
            col_de, col_pl = st.columns(2)
            with col_de:
                uploaded_german_zoll = st.file_uploader("1. Niemiecka Odprawa Celna", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"], accept_multiple_files=True, key="german_zoll_file_tab")
            with col_pl:
                uploaded_commercial_docs = st.file_uploader("2. Faktury (CI) & Packing Listy (PL)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg", "zip"], accept_multiple_files=True, key="commercial_docs_files_tab")

            if st.button("🚀 Przeprowadź Weryfikację Krzyżową i Zasil Bazę", type="primary", use_container_width=True):
                if not uploaded_german_zoll and not uploaded_commercial_docs:
                    st.warning("⚠️ Wgraj przynajmniej jeden plik!")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        analysis_contents = [
                            "Jesteś ekspertem celnym i systemem OCR. Przeanalizuj wgrane dokumenty.\n"
                            "Wyciągnij pozycje, łącząc je po Nazwie Produktu i Składzie Materiałowym.\n"
                            "Zwróć wynik jako czysty kod CSV ze średnikami (;) w pierwszej linii:\n"
                            "Nazwa_Produktu;Sklad_Materialowy;Ostateczny_Kod_TARIC;Masa_Netto_KG"
                        ]
                        for z_file in uploaded_german_zoll or []:
                            zoll_bytes = z_file.getvalue()
                            ext = z_file.name.split(".")[-1].lower()
                            analysis_contents.append(f"\n--- ODPRAWA CELNA ({z_file.name}) ---\n")
                            if ext in ["xlsx", "xls", "xlsm", "csv"]:
                                rows_z = process_excel_all_sheets_to_csv_rows(zoll_bytes, z_file.name)
                                analysis_contents.append("\n".join(rows_z[:1000]))
                            elif ext == "pdf": analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="application/pdf"))
                            else: analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="image/jpeg"))

                        for c_file in uploaded_commercial_docs or []:
                            c_bytes = c_file.getvalue()
                            ext = c_file.name.split(".")[-1].lower()
                            analysis_contents.append(f"\n--- DOKUMENT HANDLOWY ({c_file.name}) ---\n")
                            if ext in ["xlsx", "xls", "xlsm", "csv"]:
                                rows_c = process_excel_all_sheets_to_csv_rows(c_bytes, c_file.name)
                                analysis_contents.append("\n".join(rows_c[:1000]))
                            elif ext == "pdf": analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="application/pdf"))
                            else: analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="image/jpeg"))

                        with st.spinner("Przetwarzanie weryfikacji krzyżowej i ekstrakcja pozycji..."):
                            res_cross = safe_generate_content(client, selected_model, analysis_contents)
                            raw_text = res_cross.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
                            
                            from io import StringIO
                            valid_csv_lines = [l for l in raw_text.split('\n') if l.count(';') >= 2 or "Nazwa_Produktu" in l]
                            if valid_csv_lines:
                                df_cross = pd.read_csv(StringIO("\n".join(valid_csv_lines)), sep=";", on_bad_lines='skip')
                                proj["cross_check_df"] = df_cross.to_dict(orient="records")
                            else:
                                proj["cross_check_df"] = []
                            
                            proj["cross_check_sku_result"] = raw_text
                            save_container_data(cur_comp, cur_no, proj)
                            st.success("✅ Weryfikacja krzyżowa zakończona pomyślnie!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Błąd podczas weryfikacji: {str(e)}")

            if proj.get("cross_check_df"):
                st.markdown("---")
                st.markdown("### 📋 Edytowalna Tabela Dopasowania z Odprawy")
                df_cross_editable = pd.DataFrame(proj["cross_check_df"])
                edited_cross_df = st.data_editor(df_cross_editable, use_container_width=True, hide_index=True, num_rows="dynamic", key="cross_editor")
                upload_sku_img = st.file_uploader("📷 Wgraj zdjęcie referencyjne do bazy", type=["jpg", "jpeg", "png"], key="sku_img_upload")

                if st.button("💾 Zapisz Zweryfikowane Pozycje bezpośrednio do Bazy HS", type="primary", use_container_width=True):
                    records_to_save = []
                    for _, r in edited_cross_df.iterrows():
                        p_name = str(r.get("Nazwa_Produktu", r.get("Nazwa Produktu", ""))).strip()
                        mat = str(r.get("Sklad_Materialowy", r.get("Skład Materiałowy", ""))).strip()
                        taric = str(r.get("Ostateczny_Kod_TARIC", r.get("Ostateczny Kod TARIC", ""))).strip()
                        
                        if taric and taric != "nan":
                            records_to_save.append({
                                "Nazwa_Produktu": p_name,
                                "Sklad_Materialowy": mat,
                                "Ostateczny_Kod_TARIC": taric,
                                "Oficjalny Opis CN": "",
                                "Opcjonalne Tłumaczenie": translate_text_google(f"{p_name} ({mat})"),
                                "Status Celny": "Potwierdzony Celnie (Odprawiony)"
                            })
                    
                    if records_to_save:
                        added_cnt = update_hs_database_from_records(records_to_save, upload_sku_img, custom_status="Potwierdzony Celnie (Odprawiony)")
                        st.success(f"🎉 Zapisano i zaktualizowano **{added_cnt}** wzorców w Bazie HS!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("⚠️ Brak prawidłowych rekordów do zapisu.")

elif app_mode == "📦 Dedykowany Generator INTRASTAT (Huzar)":
    st.title("📦 Moduł INTRASTAT")
    st.info("Generator faktur XML gotowy.")
elif app_mode == "🇪🇺 Moduł CBAM (Kalkulator Emisji)":
    st.title("🇪🇺 Moduł CBAM")
    st.info("Kalkulator emisji gotowy.")
