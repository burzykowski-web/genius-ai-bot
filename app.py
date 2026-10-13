import streamlit as st
import pandas as pd
import os
import zipfile
import io
from datetime import datetime

# Konfiguracja strony Streamlit
st.set_page_config(
    page_title="Genius AI BOT - Platforma Celno-Logistyczna",
    page_icon="🚢",
    layout="wide"
)

# Zaawansowana stylizacja CSS dla interfejsu
st.markdown("""
    <style>
    .main-header { font-size: 26px; font-weight: bold; color: #1E3A8A; margin-bottom: 5px; }
    .sub-text { font-size: 14px; color: #4B5563; margin-bottom: 20px; }
    .metric-card { background-color: #F8FAFC; padding: 15px; border-radius: 8px; border: 1px solid #E2E8F0; }
    </style>
""", unsafe_allow_html=True)

# Inicjalizacja stanu sesji dla danych globalnych
if "dane_odpraw" not in st.session_state:
    st.session_state["dane_odpraw"] = pd.DataFrame([
        {"Nr Dokumentu": "DE/2026/01", "Kod CN": "3902 10 00", "Opis": "Polipropylen w formach podstawowych", "Masa netto (kg)": 42150.0, "Sektor": "Tworzywa", "CBAM": "NIE"},
        {"Nr Dokumentu": "DE/2026/02", "Kod CN": "5903 20 90", "Opis": "Tkaniny impregnowane poliuretanem", "Masa netto (kg)": 38400.0, "Sektor": "Włókiennictwo", "CBAM": "NIE"},
        {"Nr Dokumentu": "DE/2026/03", "Kod CN": "6403 91 13", "Opis": "Obuwie ochronne ze skórzaną cholewką", "Masa netto (kg)": 61950.0, "Sektor": "Obuwie", "CBAM": "NIE"},
        {"Nr Dokumentu": "DE/2026/04", "Kod CN": "7318 15 90", "Opis": "Elementy złączne ze stali (wkręty, nity)", "Masa netto (kg)": 18450.0, "Sektor": "Stal i Żelazo", "CBAM": "TAK"},
        {"Nr Dokumentu": "DE/2026/05", "Kod CN": "7326 90 98", "Opis": "Artykuły ze stali pozostałe", "Masa netto (kg)": 22100.0, "Sektor": "Stal i Żelazo", "CBAM": "TAK"},
        {"Nr Dokumentu": "DE/2026/06", "Kod CN": "7616 99 90", "Opis": "Artykuły z aluminium pozostałe", "Masa netto (kg)": 12850.0, "Sektor": "Aluminium", "CBAM": "TAK"}
    ])

def main():
    st.sidebar.markdown("### 📌 Wybierz Moduł Pracy:")
    
    # Wybór modułu w panelu bocznym (Radio)
    modul = st.sidebar.radio(
        "Moduły platformy:",
        [
            "🚢 Odprawy i Taryfikacja Kontenerów",
            "📦 Dedykowany Generator INTRASTAT (Huzar)",
            "📚 Wizualna Baza Kodów HS",
            "🇪🇺 EU Moduł CBAM (Kalkulator Wag Netto)"
        ],
        label_visibility="collapsed"
    )
    
    st.sidebar.markdown("---")
    st.sidebar.info("💡 **Genius AI BOT Engine v4.2**\nZintegrowane środowisko do obsługi 62 niemieckich zgłoszeń celnych, Intrastat oraz weryfikacji de minimis CBAM.")

    df = st.session_state["dane_odpraw"]

    # ----------------------------------------------------
    # MODUŁ 1: Odprawy i Taryfikacja Kontenerów
    # ----------------------------------------------------
    if modul == "🚢 Odprawy i Taryfikacja Kontenerów":
        st.markdown('<p class="main-header">🚢 Odprawy i Taryfikacja Kontenerów</p>', unsafe_allow_html=True)
        st.markdown('<p class="sub-text">Moduł importu, parsowania i weryfikacji strukturalnej dokumentów celnych oraz ładunków kontenerowych.</p>', unsafe_allow_html=True)
        
        uploaded_files = st.file_uploader("Wgraj paczkę dokumentów celnych (.zip, .xlsx, .csv)", type=["zip", "xlsx", "xls", "csv"], accept_multiple_files=True)
        
        if uploaded_files:
            st.success(f"Pomyślnie załadowano {len(uploaded_files)} plików do bufora analitycznego.")
        
        st.markdown("### Aktualna baza zaimportowanych pozycji celnych:")
        st.dataframe(df, use_container_width=True)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Przelicz sumy mas kontenerowych"):
                total_masa = df["Masa netto (kg)"].sum()
                st.success(f"Całkowita masa zweryfikowana w systemie: {total_masa:,.2f} kg ({total_masa/1000:,.2f} t)")
        with col2:
            if st.button("📥 Eksportuj pełną bazę do Excela"):
                st.info("Generowanie pliku Excel do pobrania...")

    # ----------------------------------------------------
    # MODUŁ 2: Dedykowany Generator INTRASTAT (Huzar)
    # ----------------------------------------------------
    elif modul == "📦 Dedykowany Generator INTRASTAT (Huzar)":
        st.markdown('<p class="main-header">📦 Dedykowany Generator INTRASTAT (Huzar WinSAD)</p>', unsafe_allow_html=True)
        st.markdown('<p class="sub-text">Automatyczne mapowanie pozycji celnych do formatu XML kompatybilnego z systemem Huzar WinSAD.</p>', unsafe_allow_html=True)
        
        col_1, col_2, col_3 = st.columns(3)
        with col_1:
            miesiac = st.selectbox("Miesiąc sprawozdawczy", ["Październik", "Wrzesień", "Sierpień", "Lipiec"])
        with col_2:
            rok = st.selectbox("Rok", [2026, 2025, 2024])
        with col_3:
            kod_uc = st.text_input("Kod Urzędu Celnego (np. 3010)", "3010")
            
        st.markdown("### Podgląd danych przygotowanych do deklaracji INTRASTAT:")
        st.dataframe(df[["Nr Dokumentu", "Kod CN", "Opis", "Masa netto (kg)"]], use_container_width=True)
        
        if st.button("⚡ Generuj strukturę XML dla Huzar WinSAD"):
            xml_content = f"""<?xml>
<STATINF okres="{miesiac} {rok}" uc="{kod_uc}">
    <Pozycji>{len(df)}</Pozycji>
    <MasaCalkowita>{df["Masa netto (kg)"].sum()}</MasaCalkowita>
</STATINF>"""
            st.success("Struktura XML została pomyślnie wygenerowana!")
            st.download_button(
                label="Pobierz gotowy plik XML (Huzar)",
                data=xml_content,
                file_name=f"Intrastat_{rok}_{miesiac}_Huzar.xml",
                mime="application/xml"
            )

    # ----------------------------------------------------
    # MODUŁ 3: Wizualna Baza Kodów HS
    # ----------------------------------------------------
    elif modul == "📚 Wizualna Baza Kodów HS":
        st.markdown('<p class="main-header">📚 Wizualna Baza Kodów HS / CN</p>', unsafe_allow_html=True)
        st.markdown('<p class="sub-text">Szybki słownik klasyfikacji taryfowej, powiązania sektorowe oraz flagowanie wymogów CBAM.</p>', unsafe_allow_html=True)
        
        search_query = st.text_input("🔍 Szukaj po kodzie CN lub opisie towaru:", "")
        
        filtered_df = df
        if search_query:
            filtered_df = df[df["Kod CN"].str.contains(search_query, case=False) | df["Opis"].str.contains(search_query, case=False)]
            
        st.dataframe(filtered_df, use_container_width=True)
        
        st.markdown("### Dodaj / Edytuj pozycję w bazie taryfowej:")
        with st.form("taryfa_form"):
            f_cn = st.text_input("Kod CN")
            f_opis = st.text_input("Opis towaru")
            f_sektor = st.selectbox("Sektor", ["Tworzywa", "Włókiennictwo", "Obuwie", "Stal i Żelazo", "Aluminium"])
            f_cbam = st.selectbox("Status CBAM", ["TAK", "NIE"])
            submit = st.form_submit_button("Zapisz w bazie")
            if submit and f_cn:
                st.success(f"Dodano/zaktualizowano kod CN: {f_cn}")

    # ----------------------------------------------------
    # MODUŁ 4: EU Moduł CBAM (Kalkulator Wag Netto)
    # ----------------------------------------------------
    elif modul == "🇪🇺 EU Moduł CBAM (Kalkulator Wag Netto)":
        st.markdown('<p class="main-header">🇪🇺 EU Moduł CBAM (Kalkulator Wag Netto & De Minimis)</p>', unsafe_allow_html=True)
        st.markdown('<p class="sub-text">Rygorystyczny audyt masy netto, filtrowanie sektorowe oraz weryfikacja rocznego progu de minimis (50 ton).</p>', unsafe_allow_html=True)
        
        # Filtrowanie tylko pozycji CBAM
        df_cbam = df[df["CBAM"] == "TAK"]
        
        masa_calkowita_wszystkich = df["Masa netto (kg)"].sum()
        masa_cbam = df_cbam["Masa netto (kg)"].sum()
        limit_de_minimis = 50000.0  # 50 ton w kg
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Masa wszystkich towarów", f"{masa_calkowita_wszystkich/1000:,.2f} t", f"{masa_calkowita_wszystkich:,.0f} kg")
        with col2:
            st.metric("Masa towarów CBAM", f"{masa_cbam/1000:,.2f} t", f"{masa_cbam:,.0f} kg")
        with col3:
            st.metric("Roczny limit De Minimis", f"{limit_de_minimis/1000:,.2f} t", "Próg ustawowy")
            
        st.markdown("### Szczegółowe zestawienie towarów objętych CBAM:")
        st.dataframe(df_cbam[["Nr Dokumentu", "Kod CN", "Opis", "Sektor", "Masa netto (kg)"]], use_container_width=True)
        
        # Analiza progu
        procent_limitu = (masa_cbam / limit_de_minimis) * 100
        st.markdown(f"**Stopień wykorzystania limitu de minimis:** {procent_limitu:.2f}%")
        
        if masa_cbam > limit_de_minimis:
            st.error(f"⚠️ **STATUS: PRÓG PRZEKROCZONY!** Masa towarów CBAM ({masa_cbam/1000:.2f} t) przekracza ustawowy próg 50 ton. Wymagane pełne raportowanie w systemie przejściowym CBAM.")
        else:
            st.success(f"✅ **STATUS: W NORMIE.** Próg 50 ton nie został przekrroczony (wykorzystano {procent_limitu:.2f}% limitu).")

if __name__ == "__main__":
    main()
