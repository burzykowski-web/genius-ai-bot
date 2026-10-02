import os
from io import StringIO
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# --- CONFIG ---
st.set_page_config(
    page_title="CustomsAI Pro - Asystent Celny",
    page_icon="🚢",
    layout="wide"
)

# Stylizacja Dark Mode
st.markdown("""
    <style>
    .stApp { background-color: #0f172a; color: #f8fafc; }
    .stButton>button { background-color: #2563eb; color: white; border-radius: 8px; font-weight: 600; }
    </style>
""", unsafe_allow_html=True)

# --- INIT SESSION STATE ---
if "projects" not in st.session_state:
    st.session_state.projects = {}

if "current_container" not in st.session_state:
    st.session_state.current_container = None

# API KEY SETUP
DEFAULT_KEY = "AQ.Ab8RN6LNsWIfhgnWWSVYIZEM2O_MG3HL2o9hFVmjexwfw8RMdg"

# --- SIDEBAR ---
st.sidebar.title("🚢 CustomsAI Pro")

api_key = st.sidebar.text_input("Klucz API Gemini", value=DEFAULT_KEY, type="password")
selected_model = st.sidebar.selectbox("Model API", ["gemini-3.6-flash", "gemini-1.5-flash"])

st.sidebar.markdown("---")
st.sidebar.subheader("📦 Zarządzanie Kontenerami")

new_no = st.sidebar.text_input("Numer Nowego Kontenera", placeholder="np. CNEU4699420").upper().strip()
if st.sidebar.button("+ Dodaj Kontener", use_container_width=True):
    if new_no:
        if new_no not in st.session_state.projects:
            st.session_state.projects[new_no] = {"docs": [], "out1": "", "out2": "", "out3": ""}
        st.session_state.current_container = new_no
        st.sidebar.success(f"Aktywowano: {new_no}")
        st.rerun()

st.sidebar.markdown("---")
if st.session_state.projects:
    selected_proj = st.sidebar.selectbox(
        "Aktywne Kontenery",
        options=list(st.session_state.projects.keys()),
        index=list(st.session_state.projects.keys()).index(st.session_state.current_container) if st.session_state.current_container in st.session_state.projects else 0
    )
    st.session_state.current_container = selected_proj

    if st.sidebar.button("❌ Usuń bieżący projekt", type="secondary", use_container_width=True):
        del st.session_state.projects[st.session_state.current_container]
        st.session_state.current_container = list(st.session_state.projects.keys())[0] if st.session_state.projects else None
        st.rerun()

# --- MAIN PANEL ---
if not st.session_state.current_container:
    st.title("Aplikacja Gotowa do Pracy")
    st.info("Wpisz numer kontenera w panelu po lewej stronie i kliknij **+ Dodaj Kontener**, aby rozpocząć.")
    st.stop()

cur_no = st.session_state.current_container
proj = st.session_state.projects[cur_no]

st.title(f"Kontener: `{cur_no}`")

# WGRYWANIE DOKUMENTÓW
uploaded_files = st.file_uploader(
    "1. Dokumenty Ładunkowe (PDF, XLSX, Skany, Zdjęcia)",
    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
    accept_multiple_files=True
)

if uploaded_files:
    proj["docs"] = uploaded_files
    st.caption(f"Załączono plików: {len(uploaded_files)}")

st.markdown("---")

# FUNKCJA API
def call_ai(prompt):
    if not api_key:
        st.error("Brak klucza API!")
        return None
    try:
        client = genai.Client(api_key=api_key)
        contents = [prompt]
        for f in proj["docs"]:
            contents.append(types.Part.from_bytes(data=f.getvalue(), mime_type=f.type))
            
        with st.spinner("Przetwarzanie dokumentów przez AI... Proszę czekać."):
            res = client.models.generate_content(model=selected_model, contents=contents)
            return res.text
    except Exception as e:
        st.error(f"Błąd połączenia: {str(e)}")
        return None

# TABS
t1, t2, t3 = st.tabs(["📋 1. Kontrola Formalna", "🧩 2. Zbijanie Pozycji", "🏷️ 3. Taryfikacja TARIC"])

with t1:
    st.write("Sprawdzanie spójności stron, wag netto/brutto, Incoterms, waluty oraz obecności pieczęci i podpisów.")
    if st.button("Wykonaj Kontrolę Formalną", key="b1"):
        if not proj["docs"]:
            st.warning("Wgraj najpierw dokumenty!")
        else:
            p1 = "Jesteś agentem AI przygotowującym dokumenty importowe. Przeprowadź ETAP 1 — KONTROLĘ FORMALNĄ I PODLICZENIA. Wykryj typy dokumentów (CI, PL, BL), weryfikuj strony, walutę (wymuś z CI), Incoterms, wagi netto/brutto, ilości i spójność sum. Oceń wizualnie obecność podpisów/pieczątek. Zwróć wynik w czytelnych sekcjach."
            proj["out1"] = call_ai(p1)
    if proj["out1"]:
        st.markdown(proj["out1"])

with t2:
    st.write("Agregacja pozycji o tożsamej nazwie i składzie. Przeliczenie sumaryczne z zachowaniem numeracji POS.")
    if st.button("Wykonaj Zbijanie Pozycji", key="b2"):
        if not proj["docs"]:
            st.warning("Wgraj najpierw dokumenty!")
        else:
            p2 = "Jesteś agentem AI. Przeprowadź ETAP 2 — ZBIJANIE POZYCJI. Połącz pozycje o tej samej nazwie i materiale. Zachowaj numery POS z faktury. Zwróć wynik WYŁĄCZNIE jako czysty kod CSV rozdzielany średnikami (;) z nagłówkiem w pierwszej linii: LP;POS;Opis_EN;Opis_PL;Ilosc;Kartony;Masa_Netto;Masa_Brutto;Wartosc;Waluta"
            proj["out2"] = call_ai(p2)
            
    if proj["out2"]:
        clean_csv = proj["out2"].replace("```csv", "").replace("```markdown", "").replace("```", "").strip()
        try:
            df = pd.read_csv(StringIO(clean_csv), sep=";")
            st.dataframe(df, use_container_width=True)
            
            # Pobieranie do Excela
            csv_bytes = clean_csv.encode('utf-8-sig')
            st.download_button(
                label="📊 Pobierz arkusz Excel (.csv)",
                data=csv_bytes,
                file_name=f"Zbicie_{cur_no}.csv",
                mime="text/csv"
            )
        except:
            st.code(clean_csv)

with t3:
    st.write("Weryfikacja klasyfikacji taryfowej w formacie 10-cyfrowym ze spacjami (4-2-2-2) oraz propozycjami alternatyw.")
    if st.button("Wykonaj Taryfikację", key="b3"):
        if not proj["docs"]:
            st.warning("Wgraj najpierw dokumenty!")
        else:
            p3 = "Jesteś agentem AI. Przeprowadź ETAP 3 — TARYFIKACJA. Zaproponuj kody 10-cyfrowe TARIC/ISZTAR w układzie 4-2-2-2 (np. 3926 90 97 90). Podaj maksymalnie 2 alternatywy oraz opisowe uzasadnienie dopasowania na podstawie opisu, skrótu i zdjęć."
            proj["out3"] = call_ai(p3)
    if proj["out3"]:
        st.markdown(proj["out3"])
