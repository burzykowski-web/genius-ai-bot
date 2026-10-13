# -*- coding: utf-8 -*-
"""
Moduł 3: Wizualna Baza Kodów HS
"""
import os
import json
import time

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

def update_hs_database_from_records(records, image_file=None):
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
        taric = str(r.get("Ostateczny Kod TARIC", r.get("TARIC_PROPOSED", ""))).strip()
        cn_desc = str(r.get("Oficjalny Opis CN", "")).strip()
        opt_trans = str(r.get("Opcjonalne Tłumaczenie", "")).strip()
        
        if prod_name and taric and taric != "nan":
            key = f"{prod_name}_{material}_{taric}".lower()
            db[key] = {
                "product_name": prod_name,
                "material": material,
                "taric": taric,
                "cn_description": cn_desc,
                "optional_translation": opt_trans,
                "image": img_name or r.get("Zdjęcie wzorca", "")
            }
            updated_count += 1
    if updated_count > 0:
        save_hs_database(db)
    return updated_count
