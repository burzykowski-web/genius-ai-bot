# -*- coding: utf-8 -*-
"""
Moduł 1: Odprawy i Taryfikacja Kontenerów
"""
import pandas as pd
import re

def process_odprawy_module(file_path_or_buffer, filename=""):
    """
    Kompleksowa obsługa odpraw celnych, weryfikacji kontenerów i taryfikacji.
    Odczytuje pliki Excel/CSV, analizuje pozycje i przelicza wartości celne oraz koszty CIF/FOB.
    """
    try:
        # Rozpoznanie typu pliku
        fname_lower = str(filename).lower()
        if fname_lower.endswith('.csv'):
            df = pd.read_csv(file_path_or_buffer)
        elif fname_lower.endswith(('.xls', '.xlsx')):
            xl = pd.ExcelFile(file_path_or_buffer)
            sheet_name = xl.sheet_names[0]
            df = xl.parse(sheet_name)
        else:
            return {
                "status": "ERROR",
                "message": "Nieobsługiwany format pliku w module Odpraw. Wymagany Excel lub CSV."
            }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"Błąd wczytywania pliku w module Odpraw: {str(e)}"
        }

    # Normalizacja nagłówków kolumn
    df.columns = [str(c).strip() for c in df.columns]

    # Podstawowe przeliczenia logistyczno-celne dla kontenerów
    total_records = len(df)
    
    # Próba znalezienia kolumny z wartością / CIF
    val_col = next((col for col in df.columns if any(k in col.lower() for k in ['eur', 'cif', 'fob', 'val', 'wartość'])), None)
    total_value = pd.to_numeric(df[val_col], errors='coerce').sum() if val_col else 0.0

    # Próba znalezienia kolumny z wagą netto
    weight_col = next((col for col in df.columns if any(k in col.lower() for k in ['n.w', 'masa', 'net', 'kg'])), None)
    total_weight = pd.to_numeric(df[weight_col], errors='coerce').sum() if weight_col else 0.0

    return {
        "status": "OK",
        "module": "Odprawy i Taryfikacja Kontenerów",
        "total_positions": total_records,
        "total_value": float(total_value),
        "total_weight_kg": float(total_weight),
        "summary_table": df.head(50), # Zwraca podsumowanie pierwszych 50 pozycji
        "message": f"Pomyślnie przetworzono odprawę kontenerową ({total_records} pozycji)."
    }
