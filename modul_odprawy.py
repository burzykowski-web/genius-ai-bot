# -*- coding: utf-8 -*-
import pandas as pd
import re
from io import StringIO

def clean_numeric_value(val):
    if pd.isna(val):
        return 0.0
    s = str(val).strip()
    if not s or s.lower() in ["nan", "none", "n/d", ""]:
        return 0.0
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    s_clean = re.sub(r'[^\d.-]', '', s)
    try:
        return float(s_clean)
    except ValueError:
        return 0.0

def process_stage_2_dataframe(csv_text):
    default_cols = ["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"]
    
    if not csv_text or not isinstance(csv_text, str) or not csv_text.strip():
        return pd.DataFrame(columns=default_cols)
    
    clean_lines = []
    for line in csv_text.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        upper_l = line_s.upper()
        if "CATALOG_NO" in upper_l or "PRODUCT_NAME" in upper_l or upper_l.startswith("POS;"):
            continue
        clean_lines.append(line_s)
        
    final_csv_str = "\n".join(clean_lines)
    if not final_csv_str:
        return pd.DataFrame(columns=default_cols)
        
    try:
        df = pd.read_csv(StringIO(final_csv_str), sep=";", on_bad_lines='skip', header=0)
    except Exception:
        try:
            df = pd.read_csv(StringIO(final_csv_str), sep=",", on_bad_lines='skip', header=0)
        except Exception:
            return pd.DataFrame(columns=default_cols)
            
    if df.empty:
        return pd.DataFrame(columns=default_cols)

    # Bezpieczne mapowanie kolumn po indeksach lub nazwach
    df.columns = [str(c).strip() for c in df.columns]
    
    # Tworzymy czysty DataFrame z wymagowanymi kolumnami na podstawie dostępnych danych
    mapped_data = []
    for _, row in df.iterrows():
        row_dict = {}
        # Próbujemy wyciągnąć wartości w zależności od tego, jakie kolumny rozpoznał pandas
        row_str = " ".join([str(v) for v in row.values])
        
        # Przypisanie domyślne dla bezpieczeństwa
        inv_pos = ""
        name = ""
        material = ""
        hs = ""
        ctns = 0.0
        qty = 0.0
        nw = 0.0
        gw = 0.0
        amt = 0.0
        cur = "EUR"

        for idx, col_name in enumerate(df.columns):
            val = row.iloc[idx]
            c_low = col_name.lower()
            if "catalog" in c_low or "sku" in c_low or "positions" in c_low or "art" in c_low:
                inv_pos = str(val)
            elif "name" in c_low or "produkt" in c_low or "towar" in c_low or "desc" in c_low:
                name = str(val)
            elif "material" in c_low or "skład" in c_low or "sklad" in c_low:
                material = str(val)
            elif "hs" in c_low or "taric" in c_low or "cn" in c_low or "code" in c_low:
                hs = str(val)
            elif "ctns" in c_low or "karton" in c_low:
                ctns = clean_numeric_value(val)
            elif "quant" in c_low or "szt" in c_low or "pcs" in c_low:
                qty = clean_numeric_value(val)
            elif "nw" in c_low or "netto" in c_low:
                nw = clean_numeric_value(val)
            elif "gw" in c_low or "brutto" in c_low:
                gw = clean_numeric_value(val)
            elif "amount" in c_low or "wart" in c_low or "price" in c_low or "total" in c_low:
                amt = clean_numeric_value(val)
            elif "waluta" in c_low or "curr" in c_low:
                cur = str(val)

        # Fallback jeśli kolumny były bez nagłówków (kolejność standardowa)
        if not name and len(row.values) >= 3:
            name = str(row.values[2])
        if not material and len(row.values) >= 4:
            material = str(row.values[3])

        mapped_data.append({
            "Invoice Positions": inv_pos if inv_pos and inv_pos != "nan" else "",
            "Nazwa Produktu": name.strip().upper() if name and name != "nan" else "PRODUKT ZBIORCZY",
            "Skład Materiałowy": material.strip().upper() if material and material != "nan" else "",
            "HS CODE": hs if hs and hs != "nan" else "",
            "CTNS": ctns,
            "Quantity (pcs.)": qty,
            "N.W KGS": nw,
            "G.W KGS": gw,
            "Amount (EUR)": amt,
            "Waluta": cur if cur and cur != "nan" else "EUR"
        })

    df_clean = pd.DataFrame(mapped_data)
    df_clean = df_clean[df_clean["Nazwa Produktu"] != ""]
    if df_clean.empty:
        return pd.DataFrame(columns=default_cols)

    agg_dict = {
        "CTNS": "sum",
        "Quantity (pcs.)": "sum",
        "N.W KGS": "sum",
        "G.W KGS": "sum",
        "Amount (EUR)": "sum",
        "Invoice Positions": lambda x: ", ".join(sorted(list(set(str(v).strip() for v in x if pd.notna(v) and str(v).strip() not in ["", "nan", "None"])))) if any(pd.notna(v) for v in x) else "",
        "HS CODE": lambda x: " / ".join(sorted(list(set(str(v).strip() for v in x if pd.notna(v) and str(v).strip() not in ["", "nan", "None"])))) if any(pd.notna(v) for v in x) else "",
        "Waluta": "first"
    }

    try:
        df_grouped = df_clean.groupby(["Nazwa Produktu", "Skład Materiałowy"], as_index=False).agg(agg_dict)
    except Exception:
        df_grouped = df_clean.copy()

    if df_grouped is None or df_grouped.empty:
        return pd.DataFrame(columns=default_cols)

    for rc in default_cols:
        if rc not in df_grouped.columns and rc != "pos":
            df_grouped[rc] = 0.0 if rc in ["CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)"] else ""
    
    df_grouped = df_grouped[["Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"]]
    df_grouped.insert(0, "pos", range(1, len(df_grouped) + 1))
    
    return df_grouped

def parse_stage_3_csv(csv_text):
    if not csv_text:
        return pd.DataFrame()
    try:
        clean_lines = [l for l in csv_text.split('\n') if l.strip() and not l.upper().startswith("POS;INVOICE")]
        df = pd.read_csv(StringIO("\n".join(clean_lines)), sep=";", on_bad_lines='skip')
        return df
    except Exception:
        return pd.DataFrame()

def generate_formal_pdf_report(container_no, report_text):
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=10)
    pdf.cell(200, 10, txt=f"Raport z Audytu Kontenera: {container_no}", ln=True, align="C")
    pdf.ln(10)
    for line in report_text.split('\n'):
        safe_line = line.encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 8, txt=safe_line)
    
    output = pdf.output()
    if isinstance(output, str):
        return output.encode('latin-1', 'replace')
    return bytes(output)
