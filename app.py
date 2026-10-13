# -*- coding: utf-8 -*-
import streamlit as st

# 1. IMPORTY MODUŁÓW
from modul_odprawy import process_odprawy_module
from modul_intrastat import process_intrastat_module
from modul_baza_hs import process_baza_hs_module
from modul_cbam import process_cbam_module

st.title("Genius AI BOT | Huzar Intrastat & CBAM")

# Menu wyboru modułu (odpowiadające Twojemu zrzutowi ekranu)
wybor_modulu = st.sidebar.radio(
    "Wybierz Moduł Pracy:",
    (
        "Odprawy i Taryfikacja Kontenerów",
        "Dedykowany Generator INTRASTAT (Huzar)",
        "Wizualna Baza Kodów HS",
        "EU Moduł CBAM (Kalkulator Emisji)"
    )
)

# 2. OBSŁUGA WYBORU UŻYTKOWNIKA
if wybor_modulu == "Odprawy i Taryfikacja Kontenerów":
    st.header("🚢 Odprawy i Taryfikacja Kontenerów")
    uploaded_file = st.file_uploader("Wgraj plik z pozycjami kontenera", type=["xls", "xlsx", "csv"])
    if uploaded_file:
        res = process_odprawy_module(uploaded_file, uploaded_file.name)
        st.write(res)

elif wybor_modulu == "Dedykowany Generator INTRASTAT (Huzar)":
    st.header("📦 Generator INTRASTAT (Huzar)")
    uploaded_file = st.file_uploader("Wgraj plik Excel do Intrastat", type=["xls", "xlsx"])
    kierunek = st.selectbox("Kierunek", ["WPR (Przywóz)", "PWO (Wywóz)"])
    if uploaded_file:
        res = process_intrastat_module(uploaded_file, uploaded_file.name, direction=kierunek[:3])
        st.code(res.get("xml_output", ""), language="xml")

elif wybor_modulu == "Wizualna Baza Kodów HS":
    st.header("📚 Wizualna Baza Kodów HS")
    query = st.text_input("Szukaj kodu HS lub opisu towaru:")
    if query:
        res = process_baza_hs_module(search_query=query)
        st.dataframe(res.get("results", []))

elif wybor_modulu == "EU Moduł CBAM (Kalkulator Emisji)":
    st.header("🇪🇺 EU Moduł CBAM (Kalkulator Emisji)")
    uploaded_file = st.file_uploader("Wgraj dokument (Excel lub PDF)", type=["xls", "xlsx", "pdf"])
    if uploaded_file:
        # Uruchomienie dedykowanego, zaktualizowanego modułu CBAM
        res = process_cbam_module(uploaded_file, uploaded_file.name)
        if res["status"] == "OK":
            st.success(f"Łączna masa CBAM: **{res['total_weight_tonnes']:.3f} ton** ({res['total_weight_kg']:.2f} kg)")
            if res["threshold_exceeded"]:
                st.warning("⚠️ Próg kwartalny 50 ton został przekroczony!")
            else:
                st.info("ℹ️ Próg kwartalny 50 ton nie został przekroczony.")
            
            if not res["summary_table"].empty:
                st.dataframe(res["summary_table"])
        else:
            st.error(res["message"])
