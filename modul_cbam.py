# -*- coding: utf-8 -*-
"""
Moduł 4: EU Moduł CBAM (Kalkulator Emisji)
"""
import pandas as pd
import re

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

def _parse_excel(file_path_or_buffer):
    xl = pd.ExcelFile(file_path_or_buffer)
    sheet_name = 'HS CODE' if 'HS CODE' in xl.sheet_names else xl.sheet_names[0]
    df = xl.parse(sheet_name)
    df.columns = [str(c).strip() for c in df.columns]

    hs_col = next((col for col in df.columns if 'hs' in col.lower() or 'taric' in col.lower() or 'code' in col.lower()), None)
    df['clean_hs'] = df[hs_col].apply(lambda x: re.sub(r'\D', '', str(x))) if hs_col else ''

    # Filtrowanie towarów CBAM (stal, żelazo - 72, 73, aluminium - 76, itp.)
    cbam_filter = df['clean_hs'].str.startswith(('72', '73', '76', '2804', '2811'))
    df_cbam = df[cbam_filter].copy()

    weight_col = next((col for col in df_cbam.columns if any(k in col.lower() for k in ['n.w', 'masa', 'net', 'kg'])), None)
    df_cbam['Net_Weight_KG'] = pd.to_numeric(df_cbam[weight_col], errors='coerce').fillna(0) if weight_col else 0.0

    desc_col = next((col for col in df_cbam.columns if any(k in col.lower() for k in ['desc', 'nazwa', 'item'])), df_cbam.columns[0])
    mat_col = next((col for col in df_cbam.columns if any(k in col.lower() for k in ['mat', 'mater'])), desc_col)

    records = []
    for _, row in df_cbam.iterrows():
        records.append({
            "clean_hs": row['clean_hs'],
            "DESCRIPTION": str(row[desc_col]),
            "MATERIAL": str(row[mat_col]),
            "Net_Weight_KG": float(row['Net_Weight_KG'])
        })
    return records

def _parse_pdf(file_path_or_buffer):
    if not PDF_SUPPORT:
        raise ImportError("Brak biblioteki 'pdfplumber' do obsługi plików PDF.")
    records = []
    with pdfplumber.open(file_path_or_buffer) as pdf:
        full_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])

    for line in full_text.split('\n'):
        hs_match = re.search(r'\b(72|73|76|2804|2811)\d{2,8}\b', line.replace(' ', ''))
        if hs_match:
            clean_hs = hs_match.group(0)
            weight_matches = re.findall(r'\b\d+[\.,]?\d*\b', line)
            weight_kg = 0.0
            if weight_matches:
                for w_str in reversed(weight_matches):
                    val = float(w_str.replace(',', '.'))
                    if val > 0:
                        weight_kg = val
                        break

            records.append({
                "clean_hs": clean_hs,
                "DESCRIPTION": line.strip(),
                "MATERIAL": "Dokument PDF (CBAM)",
                "Net_Weight_KG": weight_kg
            })
    return records

def process_cbam_module(file_path_or_buffer, filename=""):
    """
    Główna funkcja modułu CBAM: obsługuje pliki Excel oraz PDF, agreguje masy i weryfikuje próg 50 ton.
    """
    fname_lower = str(filename).lower()
    is_pdf = fname_lower.endswith('.pdf') or (hasattr(file_path_or_buffer, 'name') and file_path_or_buffer.name.lower().endswith('.pdf'))

    try:
        records = _parse_pdf(file_path_or_buffer) if is_pdf else _parse_excel(file_path_or_buffer)
    except Exception as e:
        return {
            "status": "ERROR",
            "message": str(e)
        }

    if not records:
        return {
            "status": "OK",
            "summary_table": pd.DataFrame(),
            "total_weight_kg": 0.0,
            "total_weight_tonnes": 0.0,
            "threshold_exceeded": False
        }

    summary_df = pd.DataFrame(records)
    summary = summary_df.groupby(['clean_hs', 'DESCRIPTION', 'MATERIAL']).agg(
        Masa_Netto_KG=('Net_Weight_KG', 'sum'),
        Liczba_Pozycji=('Net_Weight_KG', 'count')
    ).reset_index()

    total_weight_kg = summary['Masa_Netto_KG'].sum()
    total_weight_tonnes = total_weight_kg / 1000.0
    threshold_exceeded = total_weight_tonnes > 50.0 # Weryfikacja unijnego progu kwartalnego

    return {
        "status": "OK",
        "module": "EU Moduł CBAM (Kalkulator Emisji)",
        "summary_table": summary,
        "total_weight_kg": total_weight_kg,
        "total_weight_tonnes": total_weight_tonnes,
        "threshold_exceeded": threshold_exceeded,
        "message": f"Przetworzono dane CBAM. Łączna masa: {total_weight_tonnes:.3f} ton."
    }
