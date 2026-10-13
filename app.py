# -*- coding: utf-8 -*-
import os
import json
import time
import zipfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# Importy modułów
from modul_odprawy import generate_formal_pdf_report, process_stage_2_dataframe, parse_stage_3_csv
from modul_intrastat import process_intrastat_dataframe, generate_huzarfaktury_xml
from modul_baza_hs import load_hs_database, save_hs_database
from modul_baza_hs import update_hs_database_from_records

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

def process_excel_all_sheets(f_bytes, filename="plik.xls"):
    try:
        ext = filename.split(".")[-1].lower()
        if ext == "xls":
            try:
                xl = pd.ExcelFile(BytesIO(f_bytes), engine='xlrd')
            except Exception:
                xl = pd.ExcelFile(BytesIO(f_bytes))
        else:
            xl = pd.ExcelFile(BytesIO(f_bytes))
            
        combined_str = ""
        for sheet_name in xl.sheet_names:
            df_sheet = xl.parse(sheet_name)
            if len(df_sheet) > 1000:
                df_sheet = df_sheet.head(1000)
            combined_str += f"\n=== ZAKŁADKA / ARKUSZ: {sheet_name} ===\n" + df_sheet.to_string() + "\n"
        return combined_str
    except Exception as e:
        try:
            return f_bytes.decode('utf-8', errors='ignore')
        except Exception:
            return f"[Błąd odczytu pliku Excel: {str(e)}]"

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

# ==============================================================================
# MODUŁ 3: WIZUALNA BAZA KODÓW HS
# ==============================================================================
if app_mode == "🗄️ Wizualna Baza Kodów HS":
    st.title("🗄️ Wizualna Baza Wiedzy (SKU + Nazwa + Skład + Kod CN)")
    st.caption("Przeglądaj, wyszukuj i zarządzaj wzorcami towarowymi zapamiętanymi przez system.")

    hs_db = load_hs_database()
    st.info(f"Aktualna liczba wzorców w bazie: **{len(hs_db)}**")

    search_query = st.text_input("🔍 Szukaj w bazie (wpisz SKU, nazwę, skład lub kod CN):", "").strip().lower()
    st.markdown("---")
    
    if hs_db:
        filtered_items = []
        for key, val in hs_db.items():
            sku = str(val.get("catalog_number", "")).lower()
            prod = str(val.get("product_name", "")).lower()
            mat = str(val.get("material", "")).lower()
            taric = str(val.get("taric", "")).lower()
            cn_desc = str(val.get("cn_description", "")).lower()
            
            if not search_query or (search_query in sku or search_query in prod or search_query in mat or search_query in taric or search_query in cn_desc):
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
                    st.markdown(f"**Nr Katalogowy (SKU):** `{val.get('catalog_number', 'Brak')}`")
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

# ==============================================================================
# MODUŁ 1: FIRMY I KONTENERY
# ==============================================================================
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

    if not st.session_state.current_company or not st.session_state.current_container:
        st.title("Genius AI BOT — Gotowy do Pracy")
        st.info("Wybierz firmę oraz kontener w panelu bocznym.")
    else:
        cur_comp = st.session_state.current_company
        cur_no = st.session_state.current_container
        proj = st.session_state.company_data[cur_comp][cur_no]

        st.title(f"Genius AI BOT | Firma: `{cur_comp}` ➔ Kontener: `{cur_no}`")

        uploaded_files = st.file_uploader(
            "1. Dokumenty Ładunkowe (Wgraj plik ZIP lub pojedyncze CI, PL, BL, Odprawa Chińska, Excel)",
            type=["zip", "pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
            accept_multiple_files=True
        )

        if uploaded_files:
            saved_docs = save_uploaded_files(cur_comp, cur_no, uploaded_files)
            proj["docs"] = saved_docs
            st.success(f"Zapisano i załączono dokumenty: {len(proj['docs'])} szt.")
        elif proj.get("docs"):
            st.info(f"📂 Wczytano zapisane dokumenty z dysku ({len(proj['docs'])} szt.)")

        selected_tab = st.radio(
            "Wybierz Etap Analizy",
            ["🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej (SKU)"],
            horizontal=True
        )
        st.markdown("---")

        if selected_tab == "🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej (SKU)":
            st.subheader("🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa: Niemiecka Odprawa Celna vs Dokumenty Handlowe")
            st.caption("Wgraj osobno niemieckie odprawy celne oraz dokumenty handlowe, aby system powiązał numery SKU z kodami CN i zasilił bazę.")

            col_de, col_pl = st.columns(2)
            with col_de:
                uploaded_german_zoll = st.file_uploader("1. Niemiecka Odprawa Celna (ATLAS / PDF / Excel)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"], accept_multiple_files=True, key="german_zoll_file_tab")
            with col_pl:
                uploaded_commercial_docs = st.file_uploader("2. Faktury (CI) & Packing Listy (PL)", type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg", "zip"], accept_multiple_files=True, key="commercial_docs_files_tab")

            if st.button("🚀 Przeprowadź Weryfikację Krzyżową i Zasil Bazę SKU", type="primary", use_container_width=True):
                if not uploaded_german_zoll and not uploaded_commercial_docs:
                    st.warning("⚠️ Wgraj przynajmniej jeden plik!")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        analysis_contents = [
                            "Jesteś ekspertem celnym i systemem OCR. Przeanalizuj wgrane dokumenty: niemieckie odprawy celne oraz dokumenty handlowe (CI/PL).\n"
                            "Zadanie: Wyciągnij pozycje towarowe, łącząc je w pary na podstawie Numeru Katalogowego (SKU / Artikel-Nr / ART NO.) oraz nazwy.\n"
                            "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) w pierwszej linii, bez żadnego formatowania markdown (bez ```):\n"
                            "Numer_Katalogowy;Nazwa_Produktu;Sklad_Materialowy;Ostateczny_Kod_TARIC;Masa_Netto_KG"
                        ]
                        
                        for z_file in uploaded_german_zoll or []:
                            zoll_bytes = z_file.getvalue()
                            ext = z_file.name.split(".")[-1].lower()
                            analysis_contents.append(f"\n--- ODPRAWA CELNA ({z_file.name}) ---\n")
                            if ext in ["xlsx", "xls"]:
                                analysis_contents.append(process_excel_all_sheets(zoll_bytes, z_file.name))
                            elif ext == "pdf":
                                analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="application/pdf"))
                            else:
                                analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="image/jpeg"))

                        for c_file in uploaded_commercial_docs or []:
                            c_bytes = c_file.getvalue()
                            ext = c_file.name.split(".")[-1].lower()
                            analysis_contents.append(f"\n--- DOKUMENT HANDLOWY ({c_file.name}) ---\n")
                            if ext in ["xlsx", "xls"]:
                                analysis_contents.append(process_excel_all_sheets(c_bytes, c_file.name))
                            elif ext == "pdf":
                                analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="application/pdf"))
                            else:
                                analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="image/jpeg"))

                        with st.spinner("Przetwarzanie weryfikacji krzyżowej i ekstrakcja SKU..."):
                            res_cross = genai.Client(api_key=api_key).models.generate_content(model=selected_model, contents=analysis_contents)
                            raw_text = res_cross.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
                            
                            from io import StringIO
                            valid_csv_lines = [l for l in raw_text.split('\n') if l.count(';') >= 3 or "Numer_Katalogowy" in l]
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
                st.markdown("### 📋 Edytowalna Tabela Dopasowania SKU z Odprawy")
                
                df_cross_editable = pd.DataFrame(proj["cross_check_df"])
                edited_cross_df = st.data_editor(df_cross_editable, use_container_width=True, hide_index=True, num_rows="dynamic", key="cross_editor")
                
                upload_sku_img = st.file_uploader("📷 Wgraj zdjęcie referencyjne do bazy dla tych SKU (opcjonalnie)", type=["jpg", "jpeg", "png"], key="sku_img_upload")

                if st.button("💾 Zapisz Zweryfikowane SKU bezpośrednio do Bazy HS", type="primary", use_container_width=True):
                    records_to_save = []
                    for _, r in edited_cross_df.iterrows():
                        sku_val = str(r.get("Numer_Katalogowy", r.get("Numer Katalogowy", ""))).strip()
                        p_name = str(r.get("Nazwa_Produktu", r.get("Nazwa Produktu", ""))).strip()
                        mat = str(r.get("Sklad_Materialowy", r.get("Skład Materiałowy", ""))).strip()
                        taric = str(r.get("Ostateczny_Kod_TARIC", r.get("Ostateczny Kod TARIC", ""))).strip()
                        
                        if taric and taric != "nan":
                            records_to_save.append({
                                "Numer_Katalogowy": sku_val,
                                "Nazwa_Produktu": p_name,
                                "Sklad_Materialowy": mat,
                                "Ostateczny_Kod_TARIC": taric,
                                "Oficjalny Opis CN": "",
                                "Opcjonalne Tłumaczenie": translate_text_google(f"{p_name} ({mat})"),
                                "Status Celny": "Potwierdzony Celnie (Odprawiony)"
                            })
                    
                    if records_to_save:
                        added_cnt = update_hs_database_from_records(records_to_save, upload_sku_img, custom_status="Potwierdzony Celnie (Odprawiony)")
                        st.success(f"🎉 Pomyślnie zapisano i zaktualizowano **{added_cnt}** wzorców w Wizualnej Bazie HS po numerach katalogowych (SKU)!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("⚠️ Brak prawidłowych rekordów do zapisu w tabeli.")

            elif proj.get("cross_check_sku_result"):
                st.markdown("---")
                st.text_area("Wynik analizy tekstowej:", proj["cross_check_sku_result"], height=200)

elif app_mode == "📦 Dedykowany Generator INTRASTAT (Huzar)":
    st.title("📦 Moduł INTRASTAT")
    st.info("Generator faktur XML gotowy.")
elif app_mode == "🇪🇺 Moduł CBAM (Kalkulator Emisji)":
    st.title("🇪🇺 Moduł CBAM")
    st.info("Kalkulator emisji gotowy.")
