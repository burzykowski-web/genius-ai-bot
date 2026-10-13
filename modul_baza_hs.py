# -*- coding: utf-8 -*-
"""
Moduł 3: Wizualna Baza Kodów HS (z obsługą Numerów Katalogowych / SKU oraz statusów celnych)
"""
import os
import json
import time
from datetime import datetime

DATA_DIR = "projects_data"
DB_FILE = os.path.join(DATA_DIR, "hs_database_v3.json")
IMG_DB_DIR = os.path.join(DATA_DIR, "db_images")

def load_hs_database():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_hs_database(db):
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def update_hs_database_from_records(records, image_file=None, custom_status="Zatwierdzony przez Agenta"):
    """
    Zapisuje lub aktualizuje rekordy w bazie, uwzględniając Numer Katalogowy (SKU / Artikel-Nr)
    oraz status celny i numer MRN.
    """
    if not os.path.exists(IMG_DB_DIR):
        os.makedirs(IMG_DB_DIR)
    db = load_hs_database()
    updated_count = 0
    img_name = ""
    
    if image_file:
        try:
            img_bytes = image_file.getvalue()
            if img_bytes:
                img_name = f"prod_{int(time.time())}_{image_file.name}"
                img_path = os.path.join(IMG_DB_DIR, img_name)
                with open(img_path, "wb") as out:
                    out.write(img_bytes)
        except Exception:
            pass

    for r in records:
        prod_name = str(r.get("Nazwa Produktu", "")).strip()
        material = str(r.get("Skład Materiałowy", "")).strip()
        catalog_no = str(r.get("Numer Katalogowy", r.get("Catalog_No", r.get("Artikel-Nr", "")))).strip()
        taric = str(r.get("Ostateczny Kod TARIC", r.get("TARIC_PROPOSED", ""))).strip()
        cn_desc = str(r.get("Oficjalny Opis CN", "")).strip()
        opt_trans = str(r.get("Opcjonalne Tłumaczenie", "")).strip()
        
        record_status = str(r.get("Status Celny", custom_status)).strip()
        mrn_number = str(r.get("Numer MRN / SAD", "")).strip()

        if taric and taric != "nan":
            # KLUCZOWY MECHANIZM: Numer katalogowy (SKU) ma najwyższy priorytet jako unikalny klucz w bazie!
            if catalog_no and catalog_no.lower() not in ["", "n/d", "nan", "none"]:
                key = f"sku_{catalog_no.lower()}"
            else:
                key = f"{prod_name}_{material}_{taric}".lower()
            
            existing_img = db.get(key, {}).get("image", "")
            final_img = img_name if img_name else existing_img

            db[key] = {
                "catalog_number": catalog_no,
                "product_name": prod_name,
                "material": material,
                "taric": taric,
                "cn_description": cn_desc,
                "optional_translation": opt_trans,
                "image": final_img,
                "status_celny": record_status,
                "mrn": mrn_number,
                "data_aktualizacji": datetime.now().strftime("%d.%m.%Y")
            }
            updated_count += 1
            
    if updated_count > 0:
        save_hs_database(db)
    return updated_count
