import os
import json
import threading
import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
db_lock = threading.Lock()

def get_db_connection():
    clean_url = DATABASE_URL.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    return psycopg.connect(clean_url, autocommit=True)

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mod_bot_storage (
                        key VARCHAR(50) PRIMARY KEY,
                        data JSONB NOT NULL
                    );
                """)
        print("[DATABASE] Neon PostgreSQL Schema Ready!", flush=True)
    except Exception as e:
        print(f"[DATABASE ERROR] Init failed: {e}", flush=True)

def get_default_data():
    owner_id = int(os.environ.get("OWNER_ID", "0"))
    return {
        "_id": "mod_config",
        "admins": [owner_id] if owner_id else [],
        "users": {},
        "groups": {},
        "warnings": {},
        "banned_words": [],
        "custom_replies": {},
        "settings": {
            "maintenance": False,
            "new_user_notify": True
        }
    }

def load_db():
    default_data = get_default_data()
    with db_lock:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM mod_bot_storage WHERE key = 'main_config';")
                    row = cur.fetchone()
                    if row and row[0]:
                        data = row[0]
                        if isinstance(data, str):
                            data = json.loads(data)
                        for k, v in default_data.items():
                            if k not in data:
                                data[k] = v
                        return data
                    else:
                        save_db(default_data)
                        return default_data
        except Exception as e:
            print(f"[DATABASE ERROR] Load failed: {e}", flush=True)
            return default_data

def save_db(data):
    with db_lock:
        try:
            json_payload = json.dumps(data, default=str)
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO mod_bot_storage (key, data)
                        VALUES ('main_config', %s)
                        ON CONFLICT (key) DO UPDATE
                        SET data = EXCLUDED.data;
                    """, (json_payload,))
        except Exception as e:
            print(f"[DATABASE ERROR] Save failed: {e}", flush=True)
