# -*- coding: utf-8 -*-
"""
Moduł 4: EU Moduł CBAM (Kalkulator Emisji i Audyt)
"""
import re
from fpdf import FPDF

class CBAMCustomPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(26, 54, 93)
        self.cell(0, 8, 'RAPORT ANALIZY I AUDYTU CBAM', ln=1)
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(74, 85, 104)
        self.cell(0, 5, 'Genius AI BOT | Unijny Mechanizm Dostosowywania Cen na Granicach', ln=1)
        self.set_draw_color(43, 108, 176)
        self.set_line_width(0.6)
        self.line(10, 24, 200, 24)
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(113, 128, 150)
        self.cell(0, 8, f'Strona {self.page_no()} | Genius Logistics Sp. z o.o.', align='C')

def generate_cbam_pdf_report(company_name, markdown_content):
    try:
        pdf = CBAMCustomPDF()
        pdf.set_margins(12, 12, 12)
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_fill_color(235, 248, 255)
        pdf.set_draw_color(49, 130, 206)
        pdf.rect(12, 26, 186, 10, style='DF')
        pdf.set_xy(14, 28)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_text_color(44, 82, 130)
        clean_meta = f'FIRMA: {company_name} | RAPORT SPRAWOZDAWCZY CBAM'
        pdf.cell(0, 6, clean_meta.encode('latin-1', 'replace').decode('latin-1'), ln=1)
        pdf.ln(6)
        
        safe_content = str(markdown_content).encode('latin-1', 'ignore').decode('latin-1')
        lines = safe_content.split('\n')
        
        for line in lines:
            clean_line = line.strip()
            if not clean_line:
                pdf.ln(2)
                continue
            if clean_line.startswith('###') or clean_line.startswith('##') or clean_line.startswith('#'):
                pdf.ln(3)
                pdf.set_font('Helvetica', 'B', 10)
                pdf.set_text_color(44, 82, 130)
                txt = clean_line.replace('#', '').strip()
                pdf.multi_cell(186, 5, txt)
                pdf.ln(1)
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(45, 55, 72)
            elif clean_line.startswith('-') or clean_line.startswith('*'):
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(45, 55, 72)
                text = clean_line[1:].strip()
                text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
                pdf.multi_cell(186, 4.5, f' - {text}')
            else:
                pdf.set_font('Helvetica', '', 9)
                pdf.set_text_color(45, 55, 72)
                text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_line)
                pdf.multi_cell(186, 4.5, text)
                
        pdf_bytes = pdf.output(dest='S')
        if isinstance(pdf_bytes, str):
            return pdf_bytes.encode('latin-1', 'replace')
        return bytes(pdf_bytes)
    except Exception:
        return None
