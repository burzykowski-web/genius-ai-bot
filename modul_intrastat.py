# -*- coding: utf-8 -*-
"""
Moduł 2: Dedykowany Generator INTRASTAT (Huzar)
"""
import pandas as pd
import xml.etree.ElementTree as ET
from xml.dom import minidom
from io import StringIO

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
