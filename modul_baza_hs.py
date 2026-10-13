# -*- coding: utf-8 -*-
import os
import json
import pandas as pd
from io import BytesIO

DB_FILE_PATH = "hs_database.json"

def load_hs_database():
    """Wczytuje bazę kodów HS z trwałego pliku JSON na dysku."""
    if os.path.exists(DB_FILE_PATH):
        try:
            with open(DB_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_hs_database(db_dict):
    """Zapisuje bazę kodów HS do trwałego pliku JSON na dysku."""
    try:
        with open(DB_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(db_dict, f, ensure_ascii=False, indent=2)
    except Exception as _err:
        pass

def update_hs_database_from_records(records, upload_image_file=None, custom_status="Zatwierdzony"):
    """Aktualizuje bazę danych na podstawie zatwierdzonych rekordów tabeli."""
    db = load_hs_database()
    added_count = 0
    
    img_name = ""
    if upload_image_file:
        try:
            img_dir = os.path.join("projects_data", "db_images")
            if not os.path.exists(img_dir):
                os.makedirs(img_dir)
            img_name = f"{int(time.time())}_{upload_image_file.name}"
            img_path = os.path.join(img_dir, img_name)
            with open(img_path, "wb") as out:
                out.write(upload_image_file.getvalue())
        except Exception:
            pass

    for r in records:
        sku = str(r.get("Catalog_No", r.get("Numer_Katalogowy", r.get("Numer Katalogowy", "")))).strip()
        if not sku or sku.lower() in ["nan", "none", "n/d", ""]:
            continue
            
        sku_key = f"sku_{sku.lower()}"
        p_name = str(r.get("Nazwa_Produktu", r.get("Nazwa Produktu", ""))).strip()
        mat = str(r.get("Sklad_Materialowy", r.get("Skład Materiałowy", ""))).strip()
        taric = str(r.get("Ostateczny_Kod_TARIC", r.get("TARIC_PROPOSED", r.get("CN_HS_CODE", "")))).strip()
        cn_desc = str(r.get("Oficjalny Opis CN", r.get("Reasoning", ""))).strip()
        opt_trans = str(r.get("Opcjonalne Tłumaczenie", "")).strip()
        
        if taric and taric != "nan":
            db[sku_key] = {
                "catalog_number": sku,
                "product_name": p_name,
                "material": mat,
                "taric": taric,
                "cn_description": cn_desc,
                "optional_translation": opt_trans,
                "status_celny": custom_status,
                "image": img_name if img_name else db.get(sku_key, {}).get("image", "")
            }
            added_count += 1

    save_hs_database(db)
    return added_count
