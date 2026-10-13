# -*- coding: utf-8 -*-
"""
Moduł 3: Wizualna Baza Kodów HS
"""
import pandas as pd
import os

def process_baza_hs_module(search_query="", database_path="main.xls"):
    """
    Wyszukuje kody HS/TARIC, materiały oraz opisy w zintegrowanej bazie celnej.
    """
    try:
        if not os.path.exists(database_path):
            return {
                "status": "ERROR",
                "message": f"Brak pliku bazy danych {database_path}."
            }

        xl = pd.ExcelFile(database_path)
        df = xl.parse(xl.sheet_names[0])
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Błąd odczytu bazy kodów HS: {str(e)}"
        }

    df.columns = [str(c).strip() for c in df.columns]
    
    # Identyfikacja kolumn opisu i kodu
    desc_col = next((c for c in df.columns if 'desc' in c.lower() or 'nazwa' in c.lower()), df.columns[0])
    hs_col = next((c for c in df.columns if 'hs' in c.lower() or 'taric' in c.lower()), df.columns[2] if len(df.columns) > 2 else df.columns[1])
    mat_col = next((c for c in df.columns if 'mat' in c.lower()), df.columns[1] if len(df.columns) > 1 else desc_col)

    # Filtrowanie po zapytaniu użytkownika
    if search_query:
        query = str(search_query).lower()
        mask = df[desc_col].astype(str).str.lower().str.contains(query) | df[hs_col].astype(str).str.lower().str.contains(query)
        df_filtered = df[mask]
    else:
        df_filtered = df.head(100) # Domyślnie pierwszych 100 wpisów

    results = []
    for _, row in df_filtered.iterrows():
        results.append({
            "hs_code": str(row[hs_col]),
            "description": str(row[desc_col]),
            "material": str(row[mat_col])
        })

    return {
        "status": "OK",
        "module": "Wizualna Baza Kodów HS",
        "query": search_query,
        "results_count": len(results),
        "results": results
    }
