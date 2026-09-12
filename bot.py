import os
import sys
import time
import json
import re
import random
import threading
import io
import urllib.parse
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
from datetime import datetime, timezone, timedelta

# Dynamic PostgreSQL Driver Import
try:
    import psycopg2
except ImportError:
    try:
        import psycopg as psycopg2
    except ImportError:
        psycopg2 = None

sys.stdout.reconfigure(line_buffering=True)

# ----------------- TAMPER-PROOF INTEGRITY -----------------
DEVELOPER_TAG = "@jyoex"
DEV_CHANNEL = "JYOEX NETWORK"

def _verify_integrity():
    if DEVELOPER_TAG != "@jyoex" or DEV_CHANNEL != "JYOEX NETWORK":
        print("[SECURITY] Tamper detected. Halting execution.", flush=True)
        sys.exit(1)

_verify_integrity()

# ----------------- 24/7 WEB SERVER FOR RENDER -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Dual Monitor Bot is Active 24/7 on Neon Postgres")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

    def log_message(self, format, *args):
        return

def run_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        print(f"[SERVER] Health check server active on port {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"[SERVER ERROR] Web server crashed: {e}", flush=True)

threading.Thread(target=run_server, daemon=True).start()

# ----------------- CONFIGURATION & CONSTANTS -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

RAW_SESSIONS = (
    os.environ.get("INSTAGRAM_SESSION_IDS") or 
    os.environ.get("INSTAGRAM_SESSION_ID") or 
    os.environ.get("SESSION_ID") or 
    os.environ.get("SESSION_IDS") or 
    os.environ.get("IG_SESSION", "")
)

raw_proxy = os.environ.get("PROXY_URL", "").strip()
PROXIES = {
    "http": raw_proxy,
    "https": raw_proxy
} if raw_proxy else None

ADMIN_PASSWORD = "mansour$vx"
PREMIUM_PASSWORD = "Hamzai@1"
CHECK_INTERVAL_SECONDS = 20

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", disable_web_page_preview=True)

db_lock = threading.Lock()
admin_state = {}
user_message_history = {}

# ----------------- NETWORK EXECUTION ROUTE -----------------
def execute_network_request(url, headers, cookies=None, timeout=8, allow_redirects=False):
    if PROXIES:
        try:
            r = requests.get(url, headers=headers, cookies=cookies, proxies=PROXIES, timeout=timeout, allow_redirects=allow_redirects)
            if r.status_code not in [429, 403, 502, 503]:
                return r
        except Exception:
            pass  # Direct fallback on proxy failure
    return requests.get(url, headers=headers, cookies=cookies, timeout=timeout, allow_redirects=allow_redirects)

# ----------------- BULLETPROOF SCRAPER ENGINE -----------------
def single_request_check(username, session_id=None):
    clean_username = username.strip().lower().replace("@", "")
    if not clean_username:
        return {"status": "UNKNOWN", "followers": "N/A", "following": "N/A"}

    clean_session = urllib.parse.unquote(session_id.strip()) if session_id else None
    ds_user_id = clean_session.split(":")[0] if clean_session and ":" in clean_session else ""

    # Route 1: Official Instagram Web Profile Info API
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Referer": f"https://www.instagram.com/{clean_username}/"
    }
    cookies = {"sessionid": clean_session, "ds_user_id": ds_user_id} if clean_session else {}

    try:
        api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_username}"
        r = execute_network_request(api_url, headers=api_headers, cookies=cookies, timeout=7, allow_redirects=False)

        if r.status_code == 200:
            data = r.json()
            user_data = data.get("data", {}).get("user")
            if user_data:
                return {
                    "status": "ACTIVE",
                    "followers": user_data.get("edge_followed_by", {}).get("count", 0),
                    "following": user_data.get("edge_follow", {}).get("count", 0)
                }
            return {"status": "BANNED", "followers": 0, "following": 0}
        elif r.status_code == 404:
            return {"status": "BANNED", "followers": 0, "following": 0}
        elif r.status_code in [401, 302] and session_id:
            session_pool.flag_session(session_id, f"HTTP {r.status_code} Expired")
    except Exception:
        pass

    # Route 2: Mobile Shared Data Profile Scraper (Strict Header Inspection)
    try:
        prof_url = f"https://www.instagram.com/{clean_username}/"
        prof_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        r_prof = execute_network_request(prof_url, headers=prof_headers, cookies={}, timeout=7, allow_redirects=False)

        if r_prof.status_code in [404, 410]:
            return {"status": "BANNED", "followers": 0, "following": 0}

        if r_prof.status_code == 200:
            html = r_prof.text
            if "Page Not Found" in html or "isn't available" in html or "link you followed may be broken" in html:
                return {"status": "BANNED", "followers": 0, "following": 0}

            if f'content="https://www.instagram.com/{clean_username}/"' in html or \
               f'"username":"{clean_username}"' in html or \
               'og:type" content="profile"' in html or \
               f'@{clean_username}' in html:

                f_match = re.search(r'([0-9.,kKmM]+)\s+Followers', html)
                followers = f_match.group(1) if f_match else "N/A"
                return {"status": "ACTIVE", "followers": followers, "following": "N/A"}

        # If 302 Redirect to login occurs, do NOT mark as Banned!
        if r_prof.status_code in [301, 302]:
            loc = r_prof.headers.get("Location", "")
            if f"/{clean_username}/" in loc:
                return {"status": "ACTIVE", "followers": "N/A", "following": "N/A"}
    except Exception:
        pass

    # Route 3: Android App Internal Lookup
    try:
        app_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={clean_username}"
        app_headers = {
            "User-Agent": "Instagram 278.0.0.19.115 Android (30/11; 480dpi; 1080x2176; Xiaomi; Redmi Note 10; citrus; qcom; en_US; 461427670)",
            "X-IG-App-ID": "936619743392459",
            "Accept-Language": "en-US",
            "Accept": "*/*"
        }
        r_app = execute_network_request(app_url, headers=app_headers, cookies={}, timeout=7, allow_redirects=False)
        if r_app.status_code == 200:
            u = r_app.json().get("data", {}).get("user")
            if u:
                return {
                    "status": "ACTIVE",
                    "followers": u.get("edge_followed_by", {}).get("count", 0),
                    "following": u.get("edge_follow", {}).get("count", 0)
                }
        elif r_app.status_code == 404:
            return {"status": "BANNED", "followers": 0, "following": 0}
    except Exception:
        pass

    return {"status": "UNKNOWN", "followers": "N/A", "following": "N/A"}

def test_session_health(session_id):
    clean_session = urllib.parse.unquote(session_id.strip())
    ds_user_id = clean_session.split(":")[0] if ":" in clean_session else ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "Accept": "*/*",
        "Referer": "https://www.instagram.com/"
    }
    cookies = {"sessionid": clean_session, "ds_user_id": ds_user_id}

    try:
        url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram"
        r = execute_network_request(url, headers=headers, cookies=cookies, timeout=6, allow_redirects=False)

        if r.status_code == 200:
            data = r.json()
            if data.get("data", {}).get("user"):
                return True, "Active & Verified"
            return True, "Active (Operational)"
        if r.status_code in [301, 302]:
            return False, "Redirect / Challenge"
        elif r.status_code == 401:
            return False, "401 Unauthorized"
        elif r.status_code == 403:
            return False, "403 Forbidden"
        
        return True, "Active (Standby)"
    except Exception:
        return True, "Active (Direct Mode)"

class SessionPool:
    def __init__(self, raw_string):
        self.all_sessions = [s.strip() for s in raw_string.split(",") if s.strip()]
        self.active_sessions = set()
        self.flagged_sessions = {}
        self.lock = threading.Lock()
        self.run_full_health_check()

    def run_full_health_check(self):
        with self.lock:
            self.active_sessions.clear()
            self.flagged_sessions.clear()
            print(f"[SESSION POOL] Validating {len(self.all_sessions)} session(s)...", flush=True)
            for s in self.all_sessions:
                is_valid, reason = test_session_health(s)
                if is_valid:
                    self.active_sessions.add(s)
                    print(f"[SESSION POOL] Session {s[:6]}... is VALID (🟢 Active)", flush=True)
                else:
                    self.flagged_sessions[s] = f"{reason} ({datetime.now().strftime('%I:%M %p')})"
                    print(f"[SESSION POOL] Session {s[:6]}... is FLAGGED (🔴 {reason})", flush=True)
                time.sleep(0.2)

    def reload_from_env(self):
        raw = (
            os.environ.get("INSTAGRAM_SESSION_IDS") or 
            os.environ.get("INSTAGRAM_SESSION_ID") or 
            os.environ.get("SESSION_ID") or 
            os.environ.get("SESSION_IDS") or 
            os.environ.get("IG_SESSION", "")
        )
        self.all_sessions = [s.strip() for s in raw.split(",") if s.strip()]
        self.run_full_health_check()

    def get_random_sessions(self, count=1):
        with self.lock:
            actives = list(self.active_sessions)
            if not actives:
                return []
            if len(actives) <= count:
                return actives
            return random.sample(actives, count)

    def flag_session(self, session, reason="Expired / Flagged"):
        with self.lock:
            if session in self.active_sessions:
                self.active_sessions.remove(session)
                self.flagged_sessions[session] = f"{reason} ({datetime.now().strftime('%I:%M %p')})"
                print(f"[SESSION POOL] Dynamically Flagged: {session[:8]}... Reason: {reason}", flush=True)

session_pool = SessionPool(RAW_SESSIONS)

def check_single_account(username):
    username = username.strip().lower().replace("@", "")
    if not username:
        return {"status": "UNKNOWN", "followers": "N/A", "following": "N/A"}

    sessions = session_pool.get_random_sessions(1)
    if sessions:
        res = single_request_check(username, sessions[0])
        if res["status"] in ["ACTIVE", "BANNED"]:
            return res

    return single_request_check(username, None)

# ----------------- NEON POSTGRESQL ENGINE -----------------
def get_db_connection():
    clean_url = DATABASE_URL.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    if not psycopg2:
        raise ImportError("No PostgreSQL driver found.")
    return psycopg2.connect(clean_url, sslmode="require", connect_timeout=10)

def init_postgres():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_storage (
                key VARCHAR(50) PRIMARY KEY,
                data JSONB NOT NULL
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("[DATABASE] Neon PostgreSQL Schema Verified & Initialized!", flush=True)
    except Exception as e:
        print(f"[DATABASE ERROR] Init failed: {e}", flush=True)

init_postgres()

def get_default_db_data():
    return {
        "_id": "global_config",
        "unban_monitors": {},
        "ban_monitors": {},
        "admins": [],
        "premium_users": [],
        "premium_pass_claimed": False,
        "users": {},
        "groups": [],
        "settings": {
            "maintenance": False,
            "new_user_notify": True
        },
        "stats": {
            "total_monitored": 0
        },
        "channels": [
            {"id": "c1", "name": "Jyoex", "tag": "@jyoex", "link": "https://t.me/jyoex", "color": "📢"},
            {"id": "c2", "name": "Comchater", "tag": "@Comchater", "link": "https://t.me/Comchater", "color": "📢"}
        ],
        "buttons": [
            {"name": "Sell Hub", "link": "https://t.me/+gM43iG6v-vFmYjc1", "color": "📢"}
        ],
        "media": {
            "force_join": {"type": "animation", "id": "https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyemw2YjhhNWx5endhbGl5cmZ6dmJrYXhmNDZ0bDFmbmhwZmszNHd0eiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/1cGfefKF0bSSmzyThu/giphy.gif"},
            "dm_notice": {"type": "animation", "id": "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUyYW1jdmFrdDN2anZ3a2t0cWZna2xjNG5tYWxxZWp2cWJwOWh0bno3NiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/xWIklyBVywrEjcMKWJ/giphy.gif"},
            "subscription": {"type": "animation", "id": "https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUycW84MGMwMjE4ZXdjOGpnMmhlaHVqYjIzaTR2c2FzZzY4cHBqNnN1aSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/3o7aCQtmuE6a5VybLi/giphy.gif"},
            "ub_req": {"type": "animation", "id": "https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyZTcyYTVjaGc4NmY1emdwNWo3bHZjdHdjejc5ZTV6a2dtdmZ0cDVpdyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/FB5EOw0CaaQM0/giphy.gif"},
            "ub_done": {"type": "animation", "id": "https://media3.giphy.com/media/v1.Y2lkPTZjMDliOTUycDhtZ2lpcTJqcGoxam9rM2k3cDd1Z2Vpc2hteWdxZzR5NHF1amFkYiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/bdrGSR9rPkvEoRp8dw/giphy.gif"},
            "b_req": {"type": "animation", "id": "https://media2.giphy.com/media/v1.Y2lkPTZjMDliOTUya2FmcnV4OWd5azI1NzhnMzZicG5mOHhrZmFzNHFlMW5zaTJuYXFkNiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/HyOOyynWxMxig/giphy.gif"},
            "b_done": {"type": "animation", "id": "https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUydjNzdzh1NjBhcHp0bTdvNzJmcmdjZjhseHE4c3Nqd21waHR2dGd5byZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/XOiECsEvO6PfVkEJ3P/giphy.gif"},
            "deny": {"type": "animation", "id": "https://media0.giphy.com/media/v1.Y2lkPTZjMDliOTUyZXA5MmJ6ZDFjMHc0MmZ5bTJ0ZXNqeTIxbjJpenc4bWJtcXdpcWJuZCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/33OJOxsSqv6uPVOUcA/giphy.gif"}
        }
    }

def load_db():
    default_data = get_default_db_data()
    with db_lock:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT data FROM bot_storage WHERE key = 'main_config';")
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and row[0]:
                data = row[0]
                if isinstance(data, str):
                    data = json.loads(data)

                data["channels"] = default_data["channels"]
                data["buttons"] = default_data["buttons"]

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
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO bot_storage (key, data)
                VALUES ('main_config', %s)
                ON CONFLICT (key) DO UPDATE
                SET data = EXCLUDED.data;
            """, (json_payload,))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"[DATABASE ERROR] Save failed: {e}", flush=True)

db = load_db()

# ----------------- HELPERS -----------------
IST = timezone(timedelta(hours=5, minutes=30))

def get_current_time_str():
    return datetime.now(IST).strftime("%I:%M %p")

def get_current_date_str():
    return datetime.now(IST).strftime("%d %b, %Y")

def get_full_timestamp():
    return datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")

def get_user_mention(user_id, first_name):
    clean_name = first_name.replace("<", "").replace(">", "") if first_name else "User"
    return f'<a href="tg://user?id={user_id}">{clean_name}</a>'

def get_ig_link(username):
    clean_user = username.strip().replace("@", "")
    return f'<a href="https://instagram.com/{clean_user}">@{clean_user}</a>'

def is_admin_or_owner(user_id):
    return user_id in db.get("admins", [])

def is_premium_user(user_id):
    return user_id in db.get("premium_users", []) or is_admin_or_owner(user_id)

def auto_delete_after_delay(chat_id, message_id, delay_seconds=300):
    def _delete():
        time.sleep(delay_seconds)
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    threading.Thread(target=_delete, daemon=True).start()

def register_user(user, chat_id=None):
    user_id = str(user.id)
    is_new = user_id not in db.get("users", {})

    if is_new:
        db.setdefault("users", {})[user_id] = {
            "id": user.id,
            "name": user.first_name or "Unknown",
            "username": f"@{user.username}" if user.username else "No Username",
            "joined_at": get_full_timestamp(),
            "req_count": 0
        }
        save_db(db)

        if db.get("settings", {}).get("new_user_notify", True):
            mention = get_user_mention(user.id, user.first_name)
            u_tag = f'<a href="tg://user?id={user.id}">@{user.username}</a>' if user.username else "<i>None</i>"
            alert_text = (
                "🆕 <b>New User Alert:</b>\n\n"
                f"👤 <b>Name:</b> {mention}\n"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"🔗 <b>Username:</b> {u_tag}\n"
                f"📅 <b>Date & Time:</b> <code>{get_full_timestamp()}</code>"
            )
            for adm in db.get("admins", []):
                try:
                    bot.send_message(adm, alert_text)
                except Exception as e:
                    print(f"[NOTIFY ERROR] Admin {adm}: {e}", flush=True)
    else:
        db["users"][user_id]["name"] = user.first_name or "Unknown"
        db["users"][user_id]["username"] = f"@{user.username}" if user.username else "No Username"
        save_db(db)

    if chat_id and chat_id not in db.get("groups", []):
        if chat_id < 0:
            db.setdefault("groups", []).append(chat_id)
            save_db(db)

def track_and_clean_spam(chat_id, user_id, message_id):
    if chat_id < 0:
        return
    history = user_message_history.setdefault(user_id, [])
    history.append(message_id)
    if len(history) >= 3:
        oldest = history.pop(0)
        try:
            bot.delete_message(chat_id=chat_id, message_id=oldest)
        except Exception:
            pass

def format_count(count):
    if isinstance(count, str):
        count_clean = count.replace(",", "").strip()
        if count_clean.isdigit():
            count = int(count_clean)
        else:
            return count
    if not isinstance(count, (int, float)):
        return "N/A"

    if count >= 1_000_000:
        val = count / 1_000_000
        return f"{val:.1f}M" if val % 1 != 0 else f"{int(val)}M"
    elif count >= 1_000:
        val = count / 1_000
        return f"{val:.1f}k" if val % 1 != 0 else f"{int(val)}k"
    return str(count)

def format_time_taken(seconds_elapsed):
    days = int(seconds_elapsed // 86400)
    hours = int((seconds_elapsed % 86400) // 3600)
    minutes = int((seconds_elapsed % 3600) // 60)
    seconds = int(seconds_elapsed % 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "0s"

def extract_username(message):
    if not message.text:
        return None
    parts = message.text.split()
    if len(parts) < 2:
        return None
    raw = parts[1].strip().lower().replace("@", "")
    clean = re.sub(r'[^a-z0-9._]', '', raw)
    return clean if clean else None

# ----------------- MEDIA SENDER ENGINE -----------------
def send_custom_media(chat_id, key, caption, reply_to=None, reply_markup=None):
    media_data = db.get("media", {}).get(key)

    if not media_data:
        return bot.send_message(chat_id=chat_id, text=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)

    if isinstance(media_data, str):
        m_type = "animation" if media_data.endswith(".gif") else "photo"
        m_id = media_data
    else:
        m_type = media_data.get("type", "photo")
        m_id = media_data.get("id", "")

    try:
        if m_type == "video":
            return bot.send_video(chat_id=chat_id, video=m_id, caption=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)
        elif m_type == "animation":
            return bot.send_animation(chat_id=chat_id, animation=m_id, caption=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)
        elif m_type == "photo":
            return bot.send_photo(chat_id=chat_id, photo=m_id, caption=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)
        else:
            return bot.send_photo(chat_id=chat_id, photo=m_id, caption=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)
    except Exception as e:
        print(f"[MEDIA ERROR] Fallback text: {e}", flush=True)
        return bot.send_message(chat_id=chat_id, text=caption, reply_to_message_id=reply_to, reply_markup=reply_markup)

# ----------------- FORCE JOIN VERIFICATION -----------------
def get_missing_channels(user_id):
    missing = []
    for ch in db.get("channels", []):
        try:
            member = bot.get_chat_member(ch["tag"], user_id)
            if member.status not in ['creator', 'administrator', 'member']:
                missing.append(ch)
        except Exception as e:
            print(f"[CHANNEL CHECK] Channel {ch['tag']} check notice: {e}", flush=True)
    return missing

def build_force_join_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for ch in db.get("channels", []):
        btn_label = f"{ch.get('color', '📢')} {ch['name']}"
        markup.add(types.InlineKeyboardButton(btn_label, url=ch["link"]))

    for btn in db.get("buttons", []):
        btn_label = f"{btn.get('color', '📢')} {btn['name']}"
        markup.add(types.InlineKeyboardButton(btn_label, url=btn["link"]))

    markup.add(types.InlineKeyboardButton("✅ Verify", callback_data="verify_channels"))
    return markup

def check_access(message):
    user = message.from_user
    chat = message.chat
    register_user(user, chat.id)
    track_and_clean_spam(chat.id, user.id, message.message_id)

    if is_admin_or_owner(user.id) or is_premium_user(user.id):
        return True

    missing = get_missing_channels(user.id)
    if missing:
        mention = get_user_mention(user.id, user.first_name)
        text = (
            "⚠️ <b>Access Restricted</b>\n\n"
            f"Hello {mention}, you must join all our required official channels below to access this bot:\n\n"
            "<i>Click each channel to join, then tap Verify:</i>"
        )
        send_custom_media(chat.id, "force_join", text, reply_to=message.message_id, reply_markup=build_force_join_markup())
        return False

    if db.get("settings", {}).get("maintenance", False):
        maintenance_msg = (
            "🛠 <b>System Maintenance Notice</b>\n\n"
            "Our servers are currently undergoing scheduled upgrades.\n"
            "All monitoring requests are temporarily paused."
        )
        bot.reply_to(message, maintenance_msg)
        return False

    if chat.type == "private":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Comchater", url="https://t.me/Comchater"))
        mention = get_user_mention(user.id, user.first_name)
        notice_text = (
            "ℹ️ <b>Community Only Bot</b>\n\n"
            f"Hello {mention},\n"
            "To ensure 24/7 high-speed live monitoring, all bot services are hosted inside our official discussion group."
        )
        send_custom_media(chat.id, "dm_notice", notice_text, reply_to=message.message_id, reply_markup=markup)
        return False

    return True

@bot.callback_query_handler(func=lambda call: call.data == "verify_channels")
def handle_verify_callback(call):
    missing = get_missing_channels(call.from_user.id)
    if missing:
        bot.answer_callback_query(call.id, "❌ You haven't joined all required channels yet!", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "✅ Verified! You can now use the bot.", show_alert=True)
        try:
            bot.edit_message_caption(
                caption="✅ <b>Access Granted!</b> You are verified. You can now use the bot.",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        except Exception:
            pass

# ----------------- BACKGROUND MONITOR LOOP -----------------
def monitor_loop():
    while True:
        try:
            _verify_integrity()

            unban_items = list(db.get("unban_monitors", {}).items())
            if unban_items:
                for user, info in unban_items:
                    res = check_single_account(user)
                    if res["status"] == "ACTIVE":
                        elapsed = time.time() - info.get("start_time", time.time())
                        time_str = format_time_taken(elapsed)
                        f_by = format_count(res["followers"])
                        f_to = format_count(res["following"])
                        user_mention = get_user_mention(info.get("user_id"), info.get("user_name"))
                        ig_link = get_ig_link(user)

                        caption = (
                            "🎉 <b>Instagram Account Recovered</b>\n\n"
                            f"Target: <b>{ig_link}</b>\n"
                            f"Followers: <code>{f_by}</code> | Following: <code>{f_to}</code>\n"
                            f"Time Taken: <code>{time_str}</code>\n"
                            f"Recovered at: <code>{get_current_time_str()}</code>\n\n"
                            f"👤 Requested by: {user_mention}"
                        )

                        sent_msg = send_custom_media(info["chat_id"], "ub_done", caption)
                        try:
                            bot.pin_chat_message(info["chat_id"], sent_msg.message_id)
                        except Exception:
                            pass

                        db["unban_monitors"].pop(user, None)
                        save_db(db)
                    time.sleep(1.5)

            ban_items = list(db.get("ban_monitors", {}).items())
            if ban_items:
                for user, info in ban_items:
                    res = check_single_account(user)
                    if res["status"] == "BANNED":
                        time.sleep(2)
                        recheck = check_single_account(user)
                        if recheck["status"] == "BANNED":
                            elapsed = time.time() - info.get("start_time", time.time())
                            time_str = format_time_taken(elapsed)
                            f_by = format_count(info.get("followers", "N/A"))
                            f_to = format_count(info.get("following", "N/A"))
                            user_mention = get_user_mention(info.get("user_id"), info.get("user_name"))
                            ig_link = get_ig_link(user)

                            caption = (
                                "🚫 <b>Instagram Account Banned</b>\n\n"
                                f"Target: <b>{ig_link}</b>\n"
                                f"Previous Followers: <code>{f_by}</code> | Following: <code>{f_to}</code>\n"
                                f"Time Taken: <code>{time_str}</code>\n"
                                f"Banned at: <code>{get_current_time_str()}</code>\n\n"
                                f"👤 Requested by: {user_mention}"
                            )

                            sent_msg = send_custom_media(info["chat_id"], "b_done", caption)
                            try:
                                bot.pin_chat_message(info["chat_id"], sent_msg.message_id)
                            except Exception:
                                pass

                            db["ban_monitors"].pop(user, None)
                            save_db(db)
                    time.sleep(1.5)

            time.sleep(CHECK_INTERVAL_SECONDS)
        except Exception as e:
            print(f"[MONITOR LOOP ERROR] {e}", flush=True)
            time.sleep(10)

threading.Thread(target=monitor_loop, daemon=True).start()

# ----------------- ADMIN DASHBOARD & HANDLERS -----------------
def get_admin_panel_markup():
    m_status = "🟢 ON" if db.get("settings", {}).get("maintenance", False) else "⚪ OFF"
    n_status = "🔔 ON" if db.get("settings", {}).get("new_user_notify", True) else "🔕 OFF"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📬 Mailing", callback_data="admin_mailing_select"),
        types.InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
        types.InlineKeyboardButton("🔑 Session Pool", callback_data="admin_sessions_menu"),
        types.InlineKeyboardButton(f"🛠 Maint. ({m_status})", callback_data="toggle_maintenance"),
        types.InlineKeyboardButton(f"👤 New User ({n_status})", callback_data="toggle_notify"),
        types.InlineKeyboardButton("🖼 Manage Media", callback_data="admin_media"),
        types.InlineKeyboardButton("🔘 Customize Buttons", callback_data="admin_btn_menu"),
        types.InlineKeyboardButton("👥 Manage Admins", callback_data="admin_manage"),
        types.InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")
    )
    return markup

@bot.message_handler(commands=['claim'])
def handle_claim(message):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    if is_admin_or_owner(user_id):
        bot.reply_to(message, "👑 You are already authorized as Admin. Send <code>/admin</code> to open panel.")
        return

    admin_state[user_id] = "waiting_claim_password"
    bot.reply_to(message, "🔒 <b>Secret Access Verification Required</b>\n\nPlease enter the secret claim password:")

@bot.message_handler(commands=['remove', 'unclaim'])
def handle_remove_admin(message):
    if message.chat.type != "private":
        return
    user_id = message.from_user.id
    removed = False

    if user_id in db.get("admins", []):
        db["admins"].remove(user_id)
        removed = True
    if user_id in db.get("premium_users", []):
        db["premium_users"].remove(user_id)
        removed = True

    if removed:
        save_db(db)
        bot.reply_to(message, "✅ <b>Successfully Removed!</b>\nYou have been removed from the Admin/Premium position.")
    else:
        bot.reply_to(message, "ℹ️ You do not hold any Admin or Premium position.")

@bot.message_handler(commands=['admin'])
def handle_admin(message):
    user_id = message.from_user.id
    if not is_admin_or_owner(user_id):
        bot.reply_to(message, "⛔ <b>Access Denied:</b> Send <code>/claim</code> to authenticate first.")
        return

    admin_text = (
        "🔧 <b>Administrator Control Panel</b>\n\n"
        "Welcome to the master management dashboard.\n"
        "Select an action from the options below:"
    )
    bot.reply_to(message, admin_text, reply_markup=get_admin_panel_markup())

@bot.message_handler(commands=['sessions'])
def handle_sessions_command(message):
    user_id = message.from_user.id
    if not is_admin_or_owner(user_id):
        return

    total = len(session_pool.all_sessions)
    active = len(session_pool.active_sessions)
    flagged = len(session_pool.flagged_sessions)

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton(f"🟢 Active ({active})", callback_data="sess_view_active"),
        types.InlineKeyboardButton(f"🔴 Flagged ({flagged})", callback_data="sess_view_flagged"),
        types.InlineKeyboardButton("🔄 Re-test / Reset Pool", callback_data="sess_reset_pool"),
        types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")
    )

    bot.reply_to(
        message,
        "🔑 <b>Instagram Session Pool Monitor</b>\n\n"
        f"• <b>Total Loaded:</b> <code>{total}</code>\n"
        f"• <b>Active & Working:</b> <code>{active}</code>\n"
        f"• <b>Flagged / Expired:</b> <code>{flagged}</code>\n\n"
        "Select an option below to view detailed breakdown:",
        reply_markup=markup
    )

@bot.message_handler(commands=['r', 'remove_monitor'])
def handle_remove_monitor(message):
    if not check_access(message):
        return

    username = extract_username(message)
    if not username:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/r username</code>\n<b>Example:</b> <code>/r gt5available</code>")
        return

    ig_link = get_ig_link(username)
    removed = False

    if username in db.get("unban_monitors", {}):
        db["unban_monitors"].pop(username)
        removed = True

    if username in db.get("ban_monitors", {}):
        db["ban_monitors"].pop(username)
        removed = True

    if removed:
        save_db(db)
        bot.reply_to(message, f"✅ <b>Successfully Removed!</b>\nTarget <b>{ig_link}</b> has been removed from monitoring.")
    else:
        bot.reply_to(message, f"ℹ️ Target <b>{ig_link}</b> was not found in the active monitoring list.")

# ----------------- ADMIN CALLBACK HANDLERS -----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_") or call.data.startswith("sess_") or call.data.startswith("toggle_") or call.data.startswith("set_") or call.data.startswith("see_") or call.data.startswith("del_") or call.data.startswith("btn_") or call.data.startswith("col_") or call.data.startswith("mail_") or call.data == "reset_all_media")
def handle_admin_callbacks(call):
    user_id = call.from_user.id
    if not is_admin_or_owner(user_id):
        bot.answer_callback_query(call.id, "Access Denied", show_alert=True)
        return

    data = call.data

    if data == "admin_close":
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        return

    if data == "admin_sessions_menu":
        total = len(session_pool.all_sessions)
        active = len(session_pool.active_sessions)
        flagged = len(session_pool.flagged_sessions)

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"🟢 Active ({active})", callback_data="sess_view_active"),
            types.InlineKeyboardButton(f"🔴 Flagged ({flagged})", callback_data="sess_view_flagged"),
            types.InlineKeyboardButton("🔄 Re-test / Reset Pool", callback_data="sess_reset_pool"),
            types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")
        )
        bot.edit_message_text(
            "🔑 <b>Instagram Session Pool Monitor</b>\n\n"
            f"• <b>Total Loaded:</b> <code>{total}</code>\n"
            f"• <b>Active & Working:</b> <code>{active}</code>\n"
            f"• <b>Flagged / Expired:</b> <code>{flagged}</code>\n\n"
            "Choose an option below:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    if data == "sess_view_active":
        actives = list(session_pool.active_sessions)
        if not actives:
            text = "🟢 <b>Active Sessions:</b>\n\n<i>No valid sessions working currently.</i>"
        else:
            lines = [f"{i+1}. <code>{s[:6]}...{s[-4:]}</code> (🟢 Verified & Active)" for i, s in enumerate(actives)]
            text = f"🟢 <b>Active Sessions Pool ({len(actives)}):</b>\n\n" + "\n".join(lines)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back to Sessions", callback_data="admin_sessions_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data == "sess_view_flagged":
        flagged = session_pool.flagged_sessions
        if not flagged:
            text = "🔴 <b>Flagged Sessions:</b>\n\n<i>All loaded sessions are healthy and verified!</i>"
        else:
            lines = [f"{i+1}. <code>{s[:6]}...{s[-4:]}</code>\n   ⚠️ <i>{reason}</i>" for i, (s, reason) in enumerate(flagged.items())]
            text = f"🔴 <b>Flagged / Dead Sessions ({len(flagged)}):</b>\n\n" + "\n\n".join(lines)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back to Sessions", callback_data="admin_sessions_menu"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data == "sess_reset_pool":
        bot.answer_callback_query(call.id, "🔄 Validating sessions... please wait.", show_alert=False)
        session_pool.reload_from_env()
        bot.answer_callback_query(call.id, "✅ Session Health Validation Completed!", show_alert=True)
        handle_admin_callbacks(types.CallbackQuery(call.id, call.from_user, call.message, call.chat_instance, "admin_sessions_menu"))
        return

    if data == "admin_mailing_select":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🌐 Both (Bot Users + Groups)", callback_data="mail_target_both"),
            types.InlineKeyboardButton("👤 Bot Users Only", callback_data="mail_target_users"),
            types.InlineKeyboardButton("👥 Groups Only", callback_data="mail_target_groups"),
            types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")
        )
        bot.edit_message_text(
            "📬 <b>Select Mailing Broadcast Target:</b>\n\n"
            "Choose where you want the broadcast message to be delivered:",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    if data.startswith("mail_target_"):
        target_mode = data.replace("mail_target_", "")
        admin_state[user_id] = f"waiting_broadcast_{target_mode}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚫 Cancel", callback_data="cancel_action"))
        bot.edit_message_text(
            f"📬 <b>Broadcast Mode: ({target_mode.upper()})</b>\n\n"
            "Send or <b>FORWARD</b> the message right now.\n"
            "Supports Text, Photos, GIFs, Videos, or Files.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    if data == "admin_stats":
        total_users = len(db.get("users", {}))
        total_groups = len(db.get("groups", []))
        ub_count = len(db.get("unban_monitors", {}))
        b_count = len(db.get("ban_monitors", {}))
        total_tracked = db.get("stats", {}).get("total_monitored", 0) + ub_count + b_count

        stats_text = (
            "📊 <b>Bot Real-time Analytics Dashboard</b>\n\n"
            f"👤 <b>Total Unique Users:</b> <code>{total_users:,}</code>\n"
            f"👥 <b>Active Registered Groups:</b> <code>{total_groups}</code>\n"
            f"⚡ <b>Awaiting Unban (/ub):</b> <code>{ub_count}</code>\n"
            f"🚫 <b>Awaiting Ban (/b):</b> <code>{b_count}</code>\n"
            f"📈 <b>Total Accounts Tracked:</b> <code>{total_tracked:,}</code>\n"
            f"🔑 <b>Active Sessions Loaded:</b> <code>{len(session_pool.active_sessions)} / {len(session_pool.all_sessions)}</code>\n"
            "💾 <b>Database Engine:</b> <code>Neon Serverless Postgres ⚡</code>\n"
            "🕒 <b>Server Status:</b> <code>Online 24/7 (Render)</code>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📑 View All Users List", callback_data="admin_user_list"),
            types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")
        )
        bot.edit_message_text(stats_text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data == "admin_user_list":
        users = db.get("users", {})
        if not users:
            bot.answer_callback_query(call.id, "No users registered yet.", show_alert=True)
            return

        out = io.StringIO()
        out.write("==== REGISTERED USERS DATABASE ====\n\n")
        for uid, u in users.items():
            out.write(f"ID: {uid} | Name: {u.get('name')} | Username: {u.get('username')} | Requests: {u.get('req_count', 0)} | Joined: {u.get('joined_at')}\n")

        out.seek(0)
        bio = io.BytesIO(out.getvalue().encode('utf-8'))
        bio.name = f"users_database_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        bot.send_document(call.message.chat.id, bio, caption=f"📄 Total Registered Users: <b>{len(users)}</b>")
        bot.answer_callback_query(call.id, "Database document generated.")
        return

    if data == "toggle_maintenance":
        curr = db.setdefault("settings", {}).get("maintenance", False)
        db["settings"]["maintenance"] = not curr
        save_db(db)
        state_str = "ENABLED (ON)" if not curr else "DISABLED (OFF)"
        bot.answer_callback_query(call.id, f"Maintenance Mode {state_str}", show_alert=True)
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data == "toggle_notify":
        curr = db.setdefault("settings", {}).get("new_user_notify", True)
        db["settings"]["new_user_notify"] = not curr
        save_db(db)
        state_str = "ENABLED (ON)" if not curr else "DISABLED (OFF)"
        bot.answer_callback_query(call.id, f"New User Alert {state_str}", show_alert=True)
        bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data == "admin_media":
        markup = types.InlineKeyboardMarkup(row_width=3)
        media_keys = [
            ("1️⃣ /ub Req", "ub_req"),
            ("2️⃣ /ub Done", "ub_done"),
            ("3️⃣ /b Req", "b_req"),
            ("4️⃣ /b Done", "b_done"),
            ("5️⃣ ⚠️ Deny", "deny"),
            ("6️⃣ 🚪 DM", "dm_notice"),
            ("7️⃣ 💎 Sub", "subscription"),
            ("8️⃣ 🔒 Force", "force_join")
        ]
        for name, key in media_keys:
            markup.row(
                types.InlineKeyboardButton(f"✏️ {name}", callback_data=f"set_{key}"),
                types.InlineKeyboardButton("👁️ See", callback_data=f"see_{key}"),
                types.InlineKeyboardButton("🗑 Reset", callback_data=f"del_{key}")
            )
        markup.add(
            types.InlineKeyboardButton("🔄 Reset ALL Media", callback_data="reset_all_media"),
            types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back")
        )
        bot.edit_message_text(
            "🖼 <b>Manage & Preview Media:</b>\n\n"
            "• <b>✏️ Edit</b>: Upload new GIF/Photo.\n"
            "• <b>👁️ See</b>: Preview current media.\n"
            "• <b>🗑 Reset</b>: Restore default.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    if data.startswith("see_"):
        key = data.replace("see_", "")
        bot.answer_callback_query(call.id, f"Previewing {key}...")
        send_custom_media(call.message.chat.id, key, f"👁️ <b>Preview of Media key:</b> <code>{key}</code>")
        return

    if data.startswith("del_"):
        key = data.replace("del_", "")
        default_media = get_default_db_data()["media"]
        if key in default_media:
            db.setdefault("media", {})[key] = default_media[key]
            save_db(db)
            bot.answer_callback_query(call.id, f"✅ Reset {key} to default!", show_alert=True)
        return

    if data == "reset_all_media":
        default_media = get_default_db_data()["media"]
        db["media"] = default_media
        save_db(db)
        bot.answer_callback_query(call.id, "✅ All media reset to original defaults!", show_alert=True)
        bot.edit_message_text("🔧 <b>Administrator Control Panel</b>\n\nSelect an action below:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data.startswith("set_"):
        action = data.replace("set_", "")
        admin_state[user_id] = f"waiting_media_{action}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚫 Cancel", callback_data="cancel_action"))
        bot.edit_message_text(
            f"📸 <b>Send Media for {action}</b>\n\nPlease send the Photo, GIF, Video, or Sticker right now.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )
        return

    if data == "admin_btn_menu":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for ch in db.get("channels", []):
            markup.add(
                types.InlineKeyboardButton(f"✏️ Rename: {ch['name']}", callback_data=f"btn_name_{ch['id']}"),
                types.InlineKeyboardButton(f"🎨 Color Theme: {ch.get('color', '📢')}", callback_data=f"btn_color_{ch['id']}")
            )
        markup.add(types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="admin_back"))
        bot.edit_message_text("🔘 <b>Force Join Button Customizer</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data.startswith("btn_name_"):
        cid = data.replace("btn_name_", "")
        admin_state[user_id] = f"waiting_btn_name_{cid}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🚫 Cancel", callback_data="cancel_action"))
        bot.edit_message_text(f"✏️ <b>Enter New Button Text for Channel ({cid}):</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data.startswith("btn_color_"):
        cid = data.replace("btn_color_", "")
        color_map = [("green", "🟢"), ("red", "🔴"), ("blue", "🔵"), ("yellow", "🟡"), ("purple", "🟣"), ("black", "⚫"), ("white", "⚪"), ("fire", "🔥"), ("horn", "📢")]
        markup = types.InlineKeyboardMarkup(row_width=3)
        buttons = [types.InlineKeyboardButton(sym, callback_data=f"col_{cid}_{name}") for name, sym in color_map]
        markup.add(*buttons)
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_btn_menu"))
        bot.edit_message_text(f"🎨 <b>Select Emoji for Channel ({cid}):</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data.startswith("col_"):
        parts = data.split("_")
        cid = parts[1]
        cname = parts[2]
        sym_dict = {"green": "🟢", "red": "🔴", "blue": "🔵", "yellow": "🟡", "purple": "🟣", "black": "⚫", "white": "⚪", "fire": "🔥", "horn": "📢"}
        chosen_symbol = sym_dict.get(cname, "📢")
        for ch in db.get("channels", []):
            if ch["id"] == cid:
                ch["color"] = chosen_symbol
                break
        save_db(db)
        bot.answer_callback_query(call.id, f"Color updated to {chosen_symbol}", show_alert=True)
        bot.edit_message_text("🔘 <b>Force Join Button Customizer</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data == "admin_manage":
        adms = db.get("admins", [])
        adm_lines = [f"• <code>{a}</code>" for a in adms]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="admin_back"))
        bot.edit_message_text("👥 <b>Authorized Admins:</b>\n\n" + "\n".join(adm_lines), chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
        return

    if data == "admin_back":
        bot.edit_message_text("🔧 <b>Administrator Control Panel</b>\n\nSelect an action below:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())
        return

@bot.callback_query_handler(func=lambda call: call.data == "cancel_action")
def handle_cancel_action(call):
    admin_state.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, "Action cancelled.")
    bot.edit_message_text("🔧 <b>Administrator Control Panel</b>\n\nSelect an action below:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=get_admin_panel_markup())

@bot.message_handler(content_types=['text', 'photo', 'video', 'animation', 'document', 'audio', 'voice', 'sticker'], func=lambda msg: msg.from_user.id in admin_state)
def process_admin_inputs(message):
    user_id = message.from_user.id
    state = admin_state.get(user_id)

    if state == "waiting_claim_password":
        admin_state.pop(user_id, None)
        entered_pass = message.text.strip() if message.text else ""

        if entered_pass == ADMIN_PASSWORD:
            if user_id not in db["admins"]:
                db.setdefault("admins", []).append(user_id)
                save_db(db)
            bot.reply_to(message, "👑 <b>Admin Password Verified!</b>\nYou are now assigned as Master Admin. Send <code>/admin</code> to open panel.")
            return

        elif entered_pass == PREMIUM_PASSWORD:
            if db.get("premium_pass_claimed", False):
                bot.reply_to(message, "❌ <b>Password Already Claimed!</b>\nThis password has already been claimed by another user.")
                return

            db.setdefault("premium_users", []).append(user_id)
            db["premium_pass_claimed"] = True
            save_db(db)
            bot.reply_to(message, "💎 <b>Premium Access Activated!</b>\nYou have been granted Premium User privileges.")
            return

        else:
            bot.reply_to(message, "❌ <b>Incorrect Password!</b> Access Denied.")
            return

    if message.text and message.text.lower() in ["/cancel", "cancel"]:
        admin_state.pop(user_id, None)
        bot.reply_to(message, "❌ <b>Action Cancelled.</b>", reply_markup=get_admin_panel_markup())
        return

    if state and state.startswith("waiting_broadcast_"):
        target_mode = state.replace("waiting_broadcast_", "")
        admin_state.pop(user_id, None)
        status_msg = bot.reply_to(message, "⏳ <b>Broadcasting message...</b>")

        if target_mode == "both":
            targets = list(db.get("users", {}).keys()) + db.get("groups", [])
        elif target_mode == "users":
            targets = list(db.get("users", {}).keys())
        elif target_mode == "groups":
            targets = list(db.get("groups", []))
        else:
            targets = []

        total = len(targets)
        sent = 0
        failed = 0

        for target in targets:
            try:
                target_chat_id = int(target)
                bot.copy_message(chat_id=target_chat_id, from_chat_id=message.chat.id, message_id=message.message_id)
                sent += 1
                time.sleep(0.04)
            except Exception:
                failed += 1

        report = (
            f"✅ <b>Mailing Broadcast ({target_mode.upper()}) Completed!</b>\n\n"
            f"• <b>Total Targets:</b> <code>{total}</code>\n"
            f"• <b>Delivered Successfully:</b> <code>{sent}</code>\n"
            f"• <b>Failed / Blocked:</b> <code>{failed}</code>"
        )
        bot.edit_message_text(report, chat_id=message.chat.id, message_id=status_msg.message_id)
        return

    if state and state.startswith("waiting_btn_name_"):
        cid = state.replace("waiting_btn_name_", "")
        new_name = message.text.strip()
        for ch in db.get("channels", []):
            if ch["id"] == cid:
                ch["name"] = new_name
                break
        save_db(db)
        admin_state.pop(user_id, None)
        bot.reply_to(message, f"✅ <b>Success:</b> Button text updated to: <b>{new_name}</b>", reply_markup=get_admin_panel_markup())
        return

    if state and state.startswith("waiting_media_"):
        action = state.replace("waiting_media_", "")
        m_type = "photo"
        file_id = ""

        if message.animation:
            m_type = "animation"
            file_id = message.animation.file_id
        elif message.video:
            m_type = "video"
            file_id = message.video.file_id
        elif message.photo:
            m_type = "photo"
            file_id = message.photo[-1].file_id
        elif message.sticker:
            m_type = "photo"
            file_id = message.sticker.file_id
        elif message.document:
            m_type = "animation" if message.document.mime_type == "video/mp4" else "photo"
            file_id = message.document.file_id

        if file_id:
            db.setdefault("media", {})[action] = {"type": m_type, "id": file_id}
            save_db(db)
            admin_state.pop(user_id, None)
            bot.reply_to(message, f"✅ <b>Success:</b> Media for <code>/{action}</code> updated successfully!", reply_markup=get_admin_panel_markup())
        else:
            bot.reply_to(message, "❌ Invalid media type. Please send Photo, GIF, Video, or Sticker.")

# ----------------- USER COMMAND HANDLERS -----------------
@bot.message_handler(commands=['start', 'help', 'h'])
def handle_start_help(message):
    if not check_access(message):
        return

    mention = get_user_mention(message.from_user.id, message.from_user.first_name)
    welcome_text = (
        f"👋 <b>Welcome {mention}</b>\n\n"
        "<b>Available Commands:</b>\n"
        "• <code>/ub username</code> — Monitor account recovery / unban\n"
        "• <code>/b username</code> — Monitor account for ban\n"
        "• <code>/r username</code> — Remove account from monitoring\n"
        "• <code>/status</code> — Monitored accounts list\n"
        "• <code>/remove</code> — Remove your Admin/Premium access\n"
        "• <code>/help</code> — Instructions\n\n"
        f"Powered by: {DEVELOPER_TAG}"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['ub', 'unban'])
def handle_unban_request(message):
    if not check_access(message):
        return

    username = extract_username(message)
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"
    user_mention = get_user_mention(user_id, user_name)

    if not username:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/ub username</code>\n<b>Example:</b> <code>/ub gt5available</code>")
        return

    ig_link = get_ig_link(username)

    if username in db.get("unban_monitors", {}) or username in db.get("ban_monitors", {}):
        bot.reply_to(message, f"⚠️ <b>{ig_link}</b> is already in active monitoring.\nRemove first using <code>/r {username}</code>.")
        return

    status_data = check_single_account(username)
    
    # Strict validation: ONLY add if it is genuinely BANNED
    if status_data["status"] == "ACTIVE":
        caption = (
            f"ℹ️ <b>{ig_link}</b> is already active.\n\n"
            f"👤 Requested by: {user_mention}"
        )
        send_custom_media(message.chat.id, "deny", caption, reply_to=message.message_id)
        return
    elif status_data["status"] == "UNKNOWN":
        bot.reply_to(message, f"⚠️ <b>Could not verify {ig_link} right now.</b> Instagram rate limit active. Try again in 20s.")
        return

    req_time = get_current_time_str()
    req_date = get_current_date_str()

    db.setdefault("unban_monitors", {})[username] = {
        "chat_id": message.chat.id,
        "user_id": user_id,
        "user_name": user_name,
        "start_time": time.time(),
        "requested_time": req_time,
        "requested_date": req_date
    }
    db.setdefault("stats", {})["total_monitored"] = db.get("stats", {}).get("total_monitored", 0) + 1
    if str(user_id) in db.get("users", {}):
        db["users"][str(user_id)]["req_count"] = db["users"][str(user_id)].get("req_count", 0) + 1
    save_db(db)

    caption = (
        "🔍 <b>Instagram Account Monitoring Added</b>\n\n"
        f"Target: <b>{ig_link}</b>\n"
        "You'll be notified as soon as the account is active.\n\n"
        f"👤 Requested by: {user_mention}"
    )

    send_custom_media(message.chat.id, "ub_req", caption, reply_to=message.message_id)

@bot.message_handler(commands=['b', 'ban'])
def handle_ban_request(message):
    if not check_access(message):
        return

    username = extract_username(message)
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "User"
    user_mention = get_user_mention(user_id, user_name)

    if not username:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/b username</code>\n<b>Example:</b> <code>/b gt5available</code>")
        return

    ig_link = get_ig_link(username)

    if username in db.get("ban_monitors", {}) or username in db.get("unban_monitors", {}):
        bot.reply_to(message, f"⚠️ <b>{ig_link}</b> is already in active monitoring.\nRemove first using <code>/r {username}</code>.")
        return

    status_data = check_single_account(username)

    # Strict validation: ONLY add if it is genuinely ACTIVE
    if status_data["status"] == "BANNED":
        caption = (
            f"ℹ️ <b>{ig_link}</b> is already banned or unavailable.\n\n"
            f"👤 Requested by: {user_mention}"
        )
        send_custom_media(message.chat.id, "deny", caption, reply_to=message.message_id)
        return
    elif status_data["status"] == "UNKNOWN":
        bot.reply_to(message, f"⚠️ <b>Could not verify {ig_link} right now.</b> Instagram rate limit active. Try again in 20s.")
        return

    req_time = get_current_time_str()
    req_date = get_current_date_str()

    db.setdefault("ban_monitors", {})[username] = {
        "chat_id": message.chat.id,
        "user_id": user_id,
        "user_name": user_name,
        "followers": status_data["followers"],
        "following": status_data["following"],
        "start_time": time.time(),
        "requested_time": req_time,
        "requested_date": req_date
    }
    db.setdefault("stats", {})["total_monitored"] = db.get("stats", {}).get("total_monitored", 0) + 1
    if str(user_id) in db.get("users", {}):
        db["users"][str(user_id)]["req_count"] = db["users"][str(user_id)].get("req_count", 0) + 1
    save_db(db)

    caption = (
        "🔍 <b>Instagram Account Monitoring Added</b>\n\n"
        f"Target: <b>{ig_link}</b>\n"
        f"Current Status: <code>Active</code>\n"
        "You'll be notified as soon as the account is banned.\n\n"
        f"👤 Requested by: {user_mention}"
    )

    send_custom_media(message.chat.id, "b_req", caption, reply_to=message.message_id)

@bot.message_handler(commands=['status', 's'])
def handle_status(message):
    if not check_access(message):
        return

    user_id = message.from_user.id
    unbans = db.get("unban_monitors", {})
    bans = db.get("ban_monitors", {})

    user_unbans = {u: d for u, d in unbans.items() if d.get("user_id") == user_id}
    user_bans = {u: d for u, d in bans.items() if d.get("user_id") == user_id}

    if not user_unbans and not user_bans:
        bot.reply_to(message, "ℹ️ You have no active accounts currently in your monitoring list.")
        return

    lines = ["📊 <b>Your Active Monitors</b>\n"]
    if user_unbans:
        lines.append("<b>Awaiting Recovery (/ub):</b>")
        for u, d in user_unbans.items():
            t = format_time_taken(time.time() - d["start_time"])
            ig_link = get_ig_link(u)
            lines.append(f"• <b>{ig_link}</b> (Elapsed: <code>{t}</code>)")

    if user_bans:
        lines.append("\n<b>Awaiting Ban (/b):</b>")
        for u, d in user_bans.items():
            t = format_time_taken(time.time() - d["start_time"])
            ig_link = get_ig_link(u)
            lines.append(f"• <b>{ig_link}</b> (Elapsed: <code>{t}</code>)")

    bot.reply_to(message, "\n".join(lines))

@bot.message_handler(func=lambda msg: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_unrecognized_input(message):
    user = message.from_user
    register_user(user, message.chat.id)
    track_and_clean_spam(message.chat.id, user.id, message.message_id)

    if message.chat.type != "private":
        return

    missing = get_missing_channels(user.id)
    if missing and not (is_admin_or_owner(user.id) or is_premium_user(user.id)):
        mention = get_user_mention(user.id, user.first_name)
        text = (
            "⚠️ <b>Access Restricted</b>\n\n"
            f"Hello {mention}, you must join all our required official channels below to access this bot:\n\n"
            "<i>Click each channel to join, then tap Verify:</i>"
        )
        send_custom_media(chat.id, "force_join", text, reply_to=message.message_id, reply_markup=build_force_join_markup())
        return

    mention = get_user_mention(user.id, user.first_name)
    sub_text = (
        "<b>Instagram Monitor Bot 24x7</b>\n"
        "<b>Want Subscription?</b>\n\n"
        f"Hey {mention},\n"
        f"Send your ID (<code>{user.id}</code>) token to owner to claim your Paid subscription."
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Contact Owner", url="https://t.me/talkwithhimbot"),
        types.InlineKeyboardButton("Join Main Channel", url="https://t.me/+ObinPrPz_ktkODJl")
    )

    sent = send_custom_media(message.chat.id, "subscription", sub_text, reply_to=message.message_id, reply_markup=markup)
    if sent:
        auto_delete_after_delay(message.chat.id, sent.message_id, delay_seconds=300)

def run_bot_polling():
    while True:
        try:
            print("[BOT] Clearing previous webhooks and starting Polling safely...", flush=True)
            bot.remove_webhook()
            time.sleep(3)
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"[BOT ERROR] Polling interrupted: {e}. Reconnecting in 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    _verify_integrity()
    print(f"[INIT] Dual Tracker Bot is active. Loaded Sessions: {len(session_pool.active_sessions)}", flush=True)
    run_bot_polling()
