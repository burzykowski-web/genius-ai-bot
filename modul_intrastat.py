# -*- coding: utf-8 -*-
"""
Moduł 2: Dedykowany Generator INTRASTAT (Huzar)
"""
import pandas as pd
import re
import xml.etree.ElementTree as ET

def process_intrastat_module(file_path_or_buffer, filename="", direction="WPR"):
    """
    Generuje deklarację Intrastat (W przywozie / P wywozie) zgodną ze specyfikacją Huzar WinSAD.
    """
    try:
        xl = pd.ExcelFile(file_path_or_buffer)
        df = xl.parse(xl.sheet_names[0])
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Błąd odczytu pliku dla Intrastat: {str(e)}"
        }

    df.columns = [str(c).strip() for c in df.columns]

    # Mapowanie kolumn Intrastat
    hs_col = next((col for col in df.columns if 'hs' in col.lower() or 'taric' in col.lower() or 'kod' in col.lower()), df.columns[0])
    weight_col = next((col for col in df.columns if 'n.w' in col.lower() or 'masa' in col.lower() or 'net' in col.lower()), None)
    value_col = next((col for col in df.columns if 'eur' in col.lower() or 'cif' in col.lower() or 'wartość' in col.lower()), None)

    intrastat_items = []
    for _, row in df.iterrows():
        code = re.sub(r'\D', '', str(row[hs_col]))
        if len(code) >= 8:
            net_w = float(pd.to_numeric(row[weight_col], errors='coerce')) if weight_col else 0.0
            val_eur = float(pd.to_numeric(row[value_col], errors='coerce')) if value_col else 0.0

            intrastat_items.append({
                "kod_cn": code[:8],
                "masa_netto": round(net_w, 2),
                "wartosc_faktur_eur": round(val_eur, 2)
            })

    # Generowanie struktury XML zgodnej z Huzar WinSAD
    root = ET.Element("KomunikatIntrastat")
    naglowek = ET.SubElement(root, "Naglowek")
    ET.SubElement(naglowek, "Kierunek").text = direction # WPR lub PWO
    
    pozycje = ET.SubElement(root, "Pozycje")
    for idx, item in enumerate(intrastat_items, 1):
        poz = ET.SubElement(pozycje, "Pozycja", numer=str(idx))
        ET.SubElement(poz, "KodCN").text = item["kod_cn"]
        ET.SubElement(poz, "MasaNettoKG").text = str(item["masa_netto"])
        ET.SubElement(poz, "WartoscFakturEUR").text = str(item["wartosc_faktur_eur"])

    xml_string = ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")

    return {
        "status": "OK",
        "module": "Generator INTRASTAT (Huzar)",
        "total_items": len(intrastat_items),
        "xml_output": xml_string,
        "message": "Wygenerowano plik XML Intrastat gotowy do importu do Huzar WinSAD."
    }
