# -*- coding: utf-8 -*-
import os
import json
import time
from datetime import datetime

HS_DB_PATH = os.path.join("projects_data", "hs_database.json")

def load_hs_database():
    if not os.path.exists(HS_DB_PATH):
        return {}
    try:
        with open(HS_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_hs_database(db_dict):
    os.makedirs(os.path.dirname(HS_DB_PATH), exist_ok=True)
    try:
        with open(HS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(db_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Błąd zapisu bazy HS: {str(e)}")

def update_hs_database_from_records(records, uploaded_img=None, custom_status="Potwierdzony Celnie (Odprawiony)"):
    db = load_hs_database()
    added_count = 0
    
    img_filename = ""
    if uploaded_img is not None:
        try:
            img_dir = os.path.join("projects_data", "db_images")
            os.makedirs(img_dir, exist_ok=True)
            img_filename = f"{int(time.time())}_{uploaded_img.name}"
            img_path = os.path.join(img_dir, img_filename)
            with open(img_path, "wb") as out:
                out.write(uploaded_img.getvalue())
        except Exception:
            pass

    for r in records:
        sku = str(r.get("Numer_Katalogowy", r.get("Numer Katalogowy", ""))).strip()
        p_name = str(r.get("
