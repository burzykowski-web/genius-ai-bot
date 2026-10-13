# -*- coding: utf-8 -*-
import pandas as pd
from io import StringIO

def process_stage_2_dataframe(csv_text):
    if not csv_text or not isinstance(csv_text, str):
        return pd.DataFrame(columns=["pos", "Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)", "Waluta"])
    
    clean_lines = []
    for line in csv_text.split('\n'):
        line_s = line.strip()
        if not line_s:
            continue
        upper_l = line_s.upper()
        # Pomijanie nagłówków systemowych lub śmieciowych powtórzeń nagłówka
        if "CATALOG_NO" in upper_l or "PRODUCT_NAME" in upper_l or upper_l.startswith("POS;CATALOG") or "PRODUCT_NAME" in line_s:
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
            
    # Normalizacja kolumn
    col_map = {}
    for c in df.columns:
        c_low = c.strip().lower()
        if "catalog" in c_low or "sku" in c_low or "artikel" in c_low:
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
    
    # Upewnienie się, że wymagane kolumny istnieją
    req_cols = ["Invoice Positions", "Nazwa Produktu", "Skład Materiałowy", "HS CODE", "CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)"]
    for rc in req_cols:
        if rc not in df.columns:
            df[rc] = 0 if "KGS" in rc or rc in ["CTNS", "Quantity (pcs.)", "Amount (EUR)"] else ""
            
    if "pos" not in df.columns:
        df.insert(0, "pos", range(1, len(df) + 1))
    if "Waluta" not in df.columns:
        df["Waluta"] = "EUR"
        
    # Konwersja typów liczbowych
    for col in ["CTNS", "Quantity (pcs.)", "N.W KGS", "G.W KGS", "Amount (EUR)"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ".").str.replace(r"[^\d.-]", "", regex=True), errors='coerce').fillna(0)
        
    return df

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
    return bytes(pdf.output())
