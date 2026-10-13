# -*- coding: utf-8 -*-
import pandas as pd
import re
from io import StringIO

def clean_numeric_value(val):
    """Bezpiecznie konwertuje dowolny format liczbowy (w tym europejski z przecinkami/kropkami) na float."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip()
    if not s or s.lower() in ["nan", "none", "n/d", ""]:
        return 0.0
    
    # Obsługa formatów z kropkami i przecinkami (np. 1.380,15 lub 407,15)
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
    if not csv_text or not isinstance(csv_text, str):
        return pd.DataFrame(columns=["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"])
    
    clean_lines = []
    for line in csv_text.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        upper_l = line_s.upper()
        if "CATALOG_NO" in upper_l or "PRODUCT_NAME" in upper_l or upper_l.startswith("POS;CATALOG"):
            if "PRODUCT_NAME" in line_s and "Material" in line_s:
                continue
        clean_lines.append(line_s)
        
    final_csv_str = "\n".join(clean_lines)
    if not final_csv_str:
        return pd.DataFrame(columns=["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"])
        
    try:
        df = pd.read_csv(StringIO(final_csv_str), sep=";", on_bad_lines='skip')
    except Exception:
        try:
            df = pd.read_csv(StringIO(final_csv_str), sep=",", on_bad_lines='skip')
        except Exception:
            return pd.DataFrame()
            
    col_map = {}
    for c in df.columns:
        c_low = c.strip().lower()
        if "catalog" in c_low or "sku" in c_low or "artikel" in c_low or "positions" in c_low:
            col_map[c] = "Invoice Positions"
        elif "name" in c_low or "produkt" in c_low or "towar" in c_low:
            col_map[c] = "Nazwa Produktu"
        elif "material" in c_low or "skład" in c_low:
            col_map[c] = "Skład Materiałowy"
        elif "hs" in c_low or "taric" in c_low or "cn" in c_low:
            col_map[c] = "HS CODE"
        elif "ctns" in c_low or "karton" in c_low:
            col_map[c] = "CTNS"
        elif "quant" in c_low or "szt" in c_low or "pcs" in c_low:
            col_map[c] = "Quantity (pcs.)"
        elif "nw" in c_low or "netto" in c_low:
            col_map[c] = "N.W KGS"
        elif "gw" in c_low or "brutto" in c_low:
            col_map[c] = "G.W KGS"
        elif "amount" in c_low or "wart" in c_low or "price" in c_low:
            col_map[c] = "Amount (EUR)"
        elif "waluta" in c_low or "curr" in c_low:
            col_map[c] = "Waluta"
        elif "pos" in c_low:
            col_map[c] = "pos"
            
    df = df.rename(columns=col_map)
    
    req_cols = ["Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)"]
    for rc in req_cols:
        if rc not in df.columns:
            df[rc] = 0.0 if "KGS" in rc or rc in ["CTNS", "Quantity (pcs.)", "Amount (EUR)"] else ""
            
    if "Waluta" not in df.columns:
        df["Waluta"] = "EUR"
        
    # Konwersja kolumn numerycznych za pomocą poprawionej funkcji
    for col in ["CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)"]:
        df[col] = df[col].apply(clean_numeric_value)

    # Standaryzacja kluczy grupowania (Nazwa + Skład)
    df["Nazwa Produktu"] = df["Nazwa Produktu"].fillna("").astype(str).str.strip().str.upper()
    df["Skład Materiałowy"] = df["Skład Materiałowy"].fillna("").astype(str).str.strip().str.upper()

    # Agregacja i sumowanie po Nazwie i Składzie Materiałowym
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

    df_grouped = df.groupby(["Nazwa Produktu", "Skład Materiałowy"], as_index=False).agg(agg_dict)
    
    # Porządkowanie kolumn i numeracja
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
