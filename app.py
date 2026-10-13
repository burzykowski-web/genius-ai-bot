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

# Importy wydzielonych modułów
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
    st.error("⚠️ Brak skonfigurowanego klucza API w ustawieniach aplikacji (Secrets). Dodaj GEMINI_API_KEY w ustawieniach Streamlit Cloud.")
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
                    c_data = {"out1": "", "out2": "", "out3": "", "calc_audit": "", "docs": [], "hs_approved": [], "cbam_data": "", "cbam_audit_result": "", "cross_check_sku_result": ""}
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
        "cbam_audit_result": data.get("cbam_audit_result", ""),
        "cross_check_sku_result": data.get("cross_check_sku_result", "")
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
        st.subheader("🔍 Etap 2: Błyskawiczny Audyt Równoległy i Weryfikacja Progu 50 Ton CBAM")
        st.info(f"Wgraj pliki handlowe, arkusze Excel (.xls/.xlsx) lub odprawy celne dla aktywnej firmy: **{st.session_state.current_company}**. System przetworzy wszystkie pliki równolegle (błyskawicznie), zsumuje masę netto i wykaże materiały CBAM.")

        if "cbam_independent_docs" not in st.session_state:
            st.session_state.cbam_independent_docs = []

        uploaded_cbam_indep = st.file_uploader(
            "Wgraj pliki do niezależnej analizy CBAM (PDF / Excel / ZIP / Niemieckie Odprawy Celne ATLAS)",
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
            st.success(f"✅ Wgrano i załączono {len(saved_indep)} plików do analizy CBAM dla firmy {st.session_state.current_company}.")

        if st.session_state.cbam_independent_docs:
            st.write(f"📂 **Załączone pliki ({len(st.session_state.cbam_independent_docs)} szt.):** " + ", ".join([d.name for d in st.session_state.cbam_independent_docs[:10]]) + ("..." if len(st.session_state.cbam_independent_docs) > 10 else ""))

            if st.button("🚀 Uruchom Błyskawiczny Audyt Równoległy CBAM", type="primary", use_container_width=True):
                if not st.session_state.current_company:
                    st.error("Wybierz najpierw firmę w panelu bocznym.")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        all_extracted_rows = []
                        
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        total_files = len(st.session_state.cbam_independent_docs)
                        
                        def process_single_file(f_item):
                            try:
                                f_bytes = f_item.getvalue()
                                if not f_bytes: return None
                                ext = f_item.name.split(".")[-1].lower()
                                
                                file_contents_prompt = (
                                    f"Jesteś precyzyjnym audytorem celnym CBAM. Analizujesz plik {f_item.name} (w tym arkusze Excel lub odprawę celną) dla firmy: {st.session_state.current_company}.\n"
                                    "Zwróć uwagę na niemieckie określenia (np. Netto-Masse, Eigenmasse, Rohmasse, Zoll) oraz nazwy kolumn w plikach Excel.\n"
                                    "Wyciągnij wszystkie pozycje towarowe w formacie CSV ze średnikami (;):\n"
                                    "Nazwa_Produktu; Kod_TARIC; Masa_Netto_KG; Czy_CBAM_TAK_NIE; Kategoria_CBAM"
                                )
                                
                                doc_parts = [file_contents_prompt]
                                if ext in ["xlsx", "xls"]:
                                    excel_text = process_excel_all_sheets(f_bytes, f_item.name)
                                    doc_parts.append(excel_text)
                                elif ext == "pdf":
                                    doc_parts.append(types.Part.from_bytes(data=f_bytes, mime_type="application/pdf"))
                                elif ext in ["jpg", "jpeg"]:
                                    doc_parts.append(types.Part.from_bytes(data=f_bytes, mime_type="image/jpeg"))
                                elif ext == "png":
                                    doc_parts.append(types.Part.from_bytes(data=f_bytes, mime_type="application/png"))
                                    
                                res_file = safe_generate_content(client, selected_model, doc_parts)
                                if res_file and res_file.text:
                                    return f"\n--- PLIK: {f_item.name} ---\n" + res_file.text
                            except Exception:
                                pass
                            return None

                        completed_count = 0
                        with ThreadPoolExecutor(max_workers=8) as executor:
                            future_to_file = {executor.submit(process_single_file, f): f for f in st.session_state.cbam_independent_docs}
                            for future in as_completed(future_to_file):
                                completed_count += 1
                                progress_bar.progress(completed_count / total_files)
                                status_text.text(f"Przetwarzanie równoległe: ukończono {completed_count}/{total_files} plików...")
                                res_text = future.result()
                                if res_text:
                                    all_extracted_rows.append(res_text)

                        dzisiejsza_data = datetime.now().strftime("%d.%m.%Y")
                        status_text.text("Generowanie ostatecznego raportu z precyzyjnym wyliczeniem wag i kosztów...")
                        
                        summary_prompt = (
                            f"Jesteś głównym biegłym ds. celnych i CBAM dla firmy: {st.session_state.current_company}.\n"
                            f"Oficjalna data sporządzenia raportu to: {dzisiejsza_data}.\n"
                            "Oto surowe dane wyciągnięte ze wszystkich wgranych plików (Excel, PDF i odprawy):\n"
                            f"{' '.join(all_extracted_rows)}\n\n"
                            "BEZWZGLĘDNE ZASADY:\n"
                            "1. Zsumuj masy netto ze wszystkich dokumentów. Pod żadnym pozorem nie zwracaj zerowych wartości.\n"
                            "2. Podaj ostateczną masę w kilogramach oraz tonach (z dokładnością do dwóch miejsc po przecinku) oraz realnie wyliczony koszt finansowy w EUR w oparciu o ceny EU ETS.\n"
                            f"3. W nagłówku raportu wpisz bezwzględnie dzisiejszą datę: {dzisiejsza_data}.\n"
                            "4. Stwórz szczegółową tabelę wyszczególniającą wyłącznie pozycje towarowe objęte CBAM (kolumny: [Nazwa Towaru | Kod TARIC/CN | Dokładna Masa Netto (kg) | Kategoria CBAM]).\n"
                            "5. Podsumuj łączną masę towarów CBAM w kilogramach oraz tonach i jednoznacznie odpowiedz, czy przekroczono próg zwolnienia de minimis wynoszący 50 ton rocznie (TAK / NIE).\n"
                            "6. Przygotuj profesjonalny, czytelny raport w formacie Markdown."
                        )

                        final_res = safe_generate_content(client, selected_model, [summary_prompt])
                        st.session_state.cbam_indep_result = final_res.text
                        
                        status_text.empty()
                        progress_bar.empty()
                        st.success("✅ Pomyślnie przetworzono pliki i wygenerowano rzetelny raport CBAM!")
                    except Exception as e:
                        st.error(f"Błąd podczas audytu: {str(e)}")

        if "cbam_indep_result" in st.session_state and st.session_state.cbam_indep_result:
            st.markdown("---")
            st.markdown(f"### 📋 Wynik Niezależnego Audytu CBAM dla Firmy: {st.session_state.current_company}")
            st.markdown(st.session_state.cbam_indep_result)
            st.markdown("---")
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                if FPDF_AVAILABLE:
                    cbam_indep_pdf_bytes = generate_cbam_pdf_report(st.session_state.current_company, st.session_state.cbam_indep_result)
                    if cbam_indep_pdf_bytes:
                        st.download_button("📄 Pobierz Raport CBAM (PDF)", data=cbam_indep_pdf_bytes, file_name=f"Raport_CBAM_Etap2_{st.session_state.current_company}.pdf", mime="application/pdf", use_container_width=True)
                    else:
                        st.info("💡 Użyj poniższego przycisku Markdown, jeśli PDF napotka ograniczenia znaków.")
            with col_d2:
                st.download_button(
                    "📥 Pobierz Pełny Raport (Format Markdown / Tekst)",
                    data=st.session_state.cbam_indep_result.encode('utf-8'),
                    file_name=f"Raport_CBAM_Etap2_{st.session_state.current_company}.md",
                    mime="text/markdown",
                    use_container_width=True
                )

# ==============================================================================
# MODUŁ 3: WIZUALNA BAZA KODÓW HS
# ==============================================================================
elif app_mode == "🗄️ Wizualna Baza Kodów HS":
    st.title("🗄️ Wizualna Baza Wiedzy (SKU + Nazwa + Skład + Kod CN)")
    st.caption("Przeglądaj, wyszukuj, importuj z plików PDF i zarządzaj wzorcami towarowymi zapamiętanymi przez system.")

    hs_db = load_hs_database()
    st.info(f"Aktualna liczba wzorców w bazie: **{len(hs_db)}**")

    st.markdown("### 📥 Masowy Import Historycznych Wzorców z Plików PDF lub Excel")
    st.caption("Wgraj pliki PDF lub pliki Excel zawierające wszystkie zakładki. Sztuczna inteligencja automatycznie je odczyta i dopisze do bazy wzorców.")
    
    uploaded_import_files = st.file_uploader("Wgraj pliki z historycznymi taryfikacjami", type=["pdf", "xlsx", "xls", "json"], accept_multiple_files=True, key="db_import_pdf_files")
    
    if uploaded_import_files:
        if st.button("⚡ Przetwarzaj pliki i zasil Bazę Wzorców", type="primary"):
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
                        excel_text = process_excel_all_sheets(f_bytes, imp_f.name)
                        prompt_excel_import = (
                            "Jesteś analitykiem celnym. Przeanalizuj poniższe dane z pliku Excel (wszystkie zakładki):\n"
                            f"{excel_text}\n\n"
                            "Wyciągnij każdą pozycję taryfową uwzględniając Numer Katalogowy (SKU/Artikel-Nr) jeśli jest dostępny.\n"
                            "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) w pierwszej linii bez dodatkowego markdown:\n"
                            "Numer_Katalogowy;Nazwa_Produktu;Sklad_Materialowy;Kod_TARIC;Opis_CN;Tlumaczenie"
                        )
                        with st.spinner(f"Odczytywanie pliku Excel: {imp_f.name}..."):
                            res_exc = safe_generate_content(client, selected_model, [prompt_excel_import])
                            clean_csv_exc = res_exc.text.replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
                            for line in clean_csv_exc.split('\n'):
                                if "Nazwa_Produktu" in line or line.count(';') < 2:
                                    continue
                                parts = line.split(';')
                                if len(parts) >= 4:
                                    sku = parts[0].strip()
                                    p_name = parts[1].strip()
                                    mat = parts[2].strip()
                                    taric = parts[3].strip()
                                    cn_desc = parts[4].strip() if len(parts) > 4 else ""
                                    opt_trans = parts[5].strip() if len(parts) > 5 else ""
                                    
                                    if taric and taric != "nan":
                                        key = f"sku_{sku.lower()}" if sku and sku.lower() not in ["", "n/d", "nan"] else f"{p_name}_{mat}_{taric}".lower()
                                        db_current[key] = {
                                            "catalog_number": sku,
                                            "product_name": p_name,
                                            "material": mat,
                                            "taric": taric,
                                            "cn_description": cn_desc,
                                            "optional_translation": opt_trans,
                                            "image": "",
                                            "status_celny": "Zatwierdzony masowo",
                                            "mrn": "",
                                            "data_aktualizacji": datetime.now().strftime("%d.%m.%Y")
                                        }
                                        total_imported += 1
                    elif ext == "pdf":
                        prompt_pdf_import = (
                            "Jesteś analitykiem celnym. Przeanalizuj ten dokument PDF zawierający historyczne taryfikacje towarów.\n"
                            "Wyciągnij każdą pozycję (uwzględniając SKU / Numer Katalogowy).\n"
                            "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) w pierwszej linii bez dodatkowego markdown:\n"
                            "Numer_Katalogowy;Nazwa_Produktu;Sklad_Materialowy;Kod_TARIC;Opis_CN;Tlumaczenie"
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
                                    if len(parts) >= 4:
                                        sku = parts[0].strip()
                                        p_name = parts[1].strip()
                                        mat = parts[2].strip()
                                        taric = parts[3].strip()
                                        cn_desc = parts[4].strip() if len(parts) > 4 else ""
                                        opt_trans = parts[5].strip() if len(parts) > 5 else ""
                                        
                                        if taric and taric != "nan":
                                            key = f"sku_{sku.lower()}" if sku and sku.lower() not in ["", "n/d", "nan"] else f"{p_name}_{mat}_{taric}".lower()
                                            db_current[key] = {
                                                "catalog_number": sku,
                                                "product_name": p_name,
                                                "material": mat,
                                                "taric": taric,
                                                "cn_description": cn_desc,
                                                "optional_translation": opt_trans,
                                                "image": "",
                                                "status_celny": "Zatwierdzony masowo",
                                                "mrn": "",
                                                "data_aktualizacji": datetime.now().strftime("%d.%m.%Y")
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
    search_query = st.text_input("🔍 Szukaj w bazie (wpisz SKU, nazwę, skład lub kod CN):", "").strip().lower()

    st.markdown("---")
    st.subheader("📋 Wyniki i Lista Wzorców")
    
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
                    st.markdown(f"**Opis CN:** {val.get('cn_description', 'N/D')}")
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
                        excel_text = process_excel_all_sheets(f_bytes, f.name)
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
                        "docs": [], "out1": "", "out2": "", "out3": "", "calc_audit": "", "hs_approved": [], "cbam_data": "", "cbam_audit_result": "", "cross_check_sku_result": ""
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
            if not proj.get("docs"): st.error("Brak załączonych plików dla tego kontenera!"); return None
            try:
                client = genai.Client(api_key=api_key)
                contents = [prompt]
                for f in proj["docs"]:
                    f_bytes = f.getvalue()
                    if not f_bytes: continue
                    if f.type == "spreadsheet":
                        excel_text = process_excel_all_sheets(f_bytes, f.name)
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
                    "ZASADA BEZWZGLĘDNA: Oddziel nazwę produktu od składu materiałowego (np. materiały takie jak: PU, IRON, WOOD, STEEL, PPE, PLASTIC itp.). Obowiązkowo wyciągnij Numer Katalogowy (SKU / Artikel-Nr) jeśli występuje.\n"
                    "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
                    "POS;Catalog_No;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
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
            ["📋 1. Kontrola Formalna i Odprawa Chińska", "🧩 2. Zbijanie Pozycji", "🏷️ 3. Taryfikacja & Weryfikacja Agenta", "🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej (SKU)"],
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
                    "Odczytaj KAŻDĄ pozycję faktury/PL z osobna oraz wyciągnij Numer Katalogowy (SKU / Artikel-Nr).\n"
                    "Zwróć wynik WYŁĄCZNIE jako czysty kod CSV ze średnikami (;) i kropką jako separatorem dziesiętnym w pierwszej linii:\n"
                    "POS;Catalog_No;Product_Name;Material;HS_CODE;CTNS;Quantity;NW_KGS;GW_KGS;Amount;Waluta"
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
                            "2. Jeśli występują różnice, wypisz je precyzyjnie w punktach."
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

        elif selected_tab == "🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa Odprawy Niemieckiej (SKU)":
            st.subheader("🇩🇪 ⇄ 🇵🇱 Weryfikacja Krzyżowa: Niemiecka Odprawa Celna vs Dokumenty Handlowe")
            st.caption("Wgraj osobno wiele niemieckich odpraw celnych oraz dokumentów handlowych (CI/PL), aby system powiązał numery katalogowe (SKU) z kodami CN i zasilił bazę inteligentnej pamięci.")

            col_de, col_pl = st.columns(2)
            with col_de:
                uploaded_german_zoll = st.file_uploader(
                    "1. Niemiecka Odprawa Celna (ATLAS / PDF / Excel)",
                    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
                    accept_multiple_files=True,
                    key="german_zoll_file_tab"
                )
            with col_pl:
                uploaded_commercial_docs = st.file_uploader(
                    "2. Faktury (CI) & Packing Listy (PL)",
                    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg", "zip"],
                    accept_multiple_files=True,
                    key="commercial_docs_files_tab"
                )

            if st.button("🚀 Przeprowadź Weryfikację Krzyżową i Zasil Bazę SKU", type="primary", use_container_width=True):
                if not uploaded_german_zoll and not uploaded_commercial_docs:
                    st.warning("⚠️ Wgraj przynajmniej jeden plik odprawy niemieckiej lub dokumentu handlowego!")
                else:
                    try:
                        client = genai.Client(api_key=api_key)
                        analysis_contents = [
                            "Jesteś ekspertem celnym i systemem OCR. Przeanalizuj wgrane dokumenty: niemieckie odprawy celne oraz dokumenty handlowe (CI/PL).\n"
                            "Zadanie: Wyciągnij pozycje towarowe, łącząc je w pary na podstawie Numeru Katalogowego (SKU / Artikel-Nr) oraz nazwy.\n"
                            "Dla każdej pozycji wyciągnij:\n"
                            "- Numer Katalogowy (SKU / Artikel-Nr)\n"
                            "- Nazwa Produktu\n"
                            "- Skład Materiałowy\n"
                            "- Ostateczny Kod CN / TARIC z niemieckiej odprawy\n"
                            "- Masa Netto (kg)\n"
                            "Zwróć wynik w przejrzystej tabeli Markdown oraz jako czysty kod CSV ze średnikami (;) na końcu w bloku kodu."
                        ]
                        
                        if uploaded_german_zoll:
                            for z_file in uploaded_german_zoll:
                                zoll_bytes = z_file.getvalue()
                                zoll_ext = z_file.name.split(".")[-1].lower()
                                analysis_contents.append(f"\n--- NIEMIECKA ODPRAWA CELNA ({z_file.name}) ---\n")
                                if zoll_ext in ["xlsx", "xls"]:
                                    analysis_contents.append(process_excel_all_sheets(zoll_bytes, z_file.name))
                                elif zoll_ext == "pdf":
                                    analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="application/pdf"))
                                elif zoll_ext in ["jpg", "jpeg"]:
                                    analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="image/jpeg"))
                                elif zoll_ext == "png":
                                    analysis_contents.append(types.Part.from_bytes(data=zoll_bytes, mime_type="application/png"))

                        if uploaded_commercial_docs:
                            for c_file in uploaded_commercial_docs:
                                c_bytes = c_file.getvalue()
                                c_ext = c_file.name.split(".")[-1].lower()
                                analysis_contents.append(f"\n--- DOKUMENT HANDLOWY ({c_file.name}) ---\n")
                                if c_ext in ["xlsx", "xls"]:
                                    analysis_contents.append(process_excel_all_sheets(c_bytes, c_file.name))
                                elif c_ext == "pdf":
                                    analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="application/pdf"))
                                elif c_ext in ["jpg", "jpeg"]:
                                    analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="image/jpeg"))
                                elif c_ext == "png":
                                    analysis_contents.append(types.Part.from_bytes(data=c_bytes, mime_type="application/png"))

                        with st.spinner("Przetwarzanie weryfikacji krzyżowej wielu plików i ekstrakcja SKU..."):
                            res_cross = safe_generate_content(client, selected_model, analysis_contents)
                            proj["cross_check_sku_result"] = res_cross.text
                            save_container_data(cur_comp, cur_no, proj)
                            st.success("✅ Weryfikacja krzyżowa zakończona pomyślnie!")
                            st.rerun()

                    except Exception as e:
                        st.error(f"Błąd podczas weryfikacji: {str(e)}")

            if proj.get("cross_check_sku_result"):
                st.markdown("---")
                st.markdown("### 📋 Wyniki Dopasowania Numerów Katalogowych (SKU)")
                st.markdown(proj["cross_check_sku_result"])

        elif selected_tab == "🏷️ 3. Taryfikacja & Weryfikacja Agenta":
            st.subheader("🏷️ Etap 3: Taryfikacja (Pamięć po SKU + Nazwa + Skład)")
            if not proj.get("out2"):
                st.warning("⚠️ Najpierw wykonaj Etap 2 (Zbijanie Pozycji)!")
            else:
                if st.button("Wykonaj Taryfikację Zbieganych Pozycji", key="b3"):
                    try:
                        df_stage2 = process_stage_2_dataframe(proj["out2"])
                        with st.spinner("Automatyczna taryfikacja (sprawdzanie pamięci po SKU i AI) w tle..."):
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
                            sku = str(row.get("Catalog_No", row.get("Numer Katalogowy", ""))).strip()
                            p_name = str(row.get("Nazwa Produktu", "")).strip()
                            mat = str(row.get("Skład Materiałowy", "")).strip()
                            proposed_code = str(row.get("TARIC_PROPOSED", row.get("CN_HS_CODE", ""))).strip()
                            proposed_cn_desc = str(row.get("Oficjalny Opis CN", row.get("Reasoning", ""))).strip()
                            
                            if "Opcjonalne Tłumaczenie" in df_t3.columns and pd.notna(row.get("Opcjonalne Tłumaczenie")):
                                proposed_opt_trans = str(row.get("Opcjonalne Tłumaczenie", "")).strip()
                            else:
                                proposed_opt_trans = translate_text_google(f"{p_name} ({mat})")
                            
                            matched_in_db = False
                            # PRIORYTET 1: Dopasowanie po Numerze Katalogowym (SKU)
                            if sku and sku.lower() not in ["", "n/d", "nan", "none"]:
                                sku_key = f"sku_{sku.lower()}"
                                if sku_key in current_db:
                                    db_v = current_db[sku_key]
                                    db_matched.append(True)
                                    final_codes.append(db_v.get("taric", proposed_code))
                                    cn_descriptions.append(db_v.get("cn_description", proposed_cn_desc))
                                    opt_translations.append(db_v.get("optional_translation", proposed_opt_trans))
                                    statuses.append("🟢 PAMIĘĆ SKU (Auto)")
                                    db_images.append(db_v.get("image", ""))
                                    matched_in_db = True

                            # PRIORYTET 2: Dopasowanie klasyczne (Nazwa + Skład + Kod)
                            if not matched_in_db:
                                for db_k, db_v in current_db.items():
                                    db_prod = str(db_v.get("product_name", "")).strip().lower()
                                    db_mat = str(db_v.get("material", "")).strip().lower()
                                    db_taric = str(db_v.get("taric", "")).strip().lower()
                                    
                                    if db_prod == p_name.lower() and db_mat == mat.lower() and db_taric == proposed_code.lower():
                                        db_matched.append(True)
                                        final_codes.append(db_v.get("taric", proposed_code))
                                        cn_descriptions.append(db_v.get("cn_description", proposed_cn_desc))
                                        opt_translations.append(db_v.get("optional_translation", proposed_opt_trans))
                                        statuses.append("🟢 BAZA (Auto)")
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

                        st.markdown("### 🤖 3A. Propozycje AI i Pamięć SKU z Bazy")
                        st.dataframe(df_t3, use_container_width=True, hide_index=True)
                        st.markdown("---")
                        st.markdown("### 👨‍💼 3B. Weryfikacja & Akceptacja Agenta Celnego")

                        if "df_editor" not in proj or not proj["hs_approved"]:
                            df_editor_init = df_t3.copy()
                            df_editor_init["Zaakceptowano"] = db_matched
                            df_editor_init["Ostateczny Kod TARIC"] = final_codes
                            df_editor_init["Status Celny"] = ["Potwierdzony Celnie (Odprawiony)" if m else "Do weryfikacji" for m in db_matched]
                        else:
                            df_editor_init = pd.DataFrame(proj["hs_approved"])

                        edited_df = st.data_editor(df_editor_init, use_container_width=True, hide_index=True, num_rows="dynamic", key=f"editor_{cur_no}")

                        st.markdown("---")
                        upload_db_img = st.file_uploader("📷 Wgraj zdjęcie referencyjne dla tych pozycji do bazy (opcjonalnie)", type=["jpg", "jpeg", "png"], key=f"img_up_{cur_no}")

                        if st.button("💾 Zatwierdź Kody HS dla Urzędu Celnego i Zapisz do Bazy (z SKU)", type="primary"):
                            records = edited_df.to_dict(orient="records")
                            proj["hs_approved"] = records
                            save_container_data(cur_comp, cur_no, proj)
                            added = update_hs_database_from_records(records, upload_db_img, custom_status="Potwierdzony Celnie (Odprawiony)")
                            st.success(f"✅ Zatwierdzono! Pomyślnie zaktualizowano **{added}** wzorców w Bazie z uwzględnieniem Numerów Katalogowych (SKU).")
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
