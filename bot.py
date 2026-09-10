import os
import sys
import time
import json
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
from datetime import datetime, timezone, timedelta
import psycopg

sys.stdout.reconfigure(line_buffering=True)

# ----------------- 24/7 WEB SERVER FOR RENDER -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Group Moderation Bot is Active 24/7 on Neon Postgres")

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
        print(f"[SERVER] Health check active on port {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"[SERVER ERROR] Crashed: {e}", flush=True)

threading.Thread(target=run_server, daemon=True).start()

# ----------------- CONFIGURATION -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
ADMIN_SECRET_KEY = "mansour$vx"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", disable_web_page_preview=True)

db_lock = threading.Lock()
admin_state = {}
user_message_history = {}
IST = timezone(timedelta(hours=5, minutes=30))

# ----------------- DATABASE ENGINE -----------------
def get_db_connection():
    clean_url = DATABASE_URL.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    return psycopg.connect(clean_url, autocommit=True, connect_timeout=10)

def init_postgres():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mod_bot_storage (
                        key VARCHAR(50) PRIMARY KEY,
                        data JSONB NOT NULL
                    );
                """)
        print("[DATABASE] Schema Verified & Ready!", flush=True)
    except Exception as e:
        print(f"[DATABASE ERROR] Init failed: {e}", flush=True)

init_postgres()

def get_default_db_data():
    return {
        "_id": "mod_config",
        "admins": [OWNER_ID] if OWNER_ID else [],
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
    default_data = get_default_db_data()
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
                        if OWNER_ID and OWNER_ID not in data.get("admins", []):
                            data.setdefault("admins", []).append(OWNER_ID)
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

db = load_db()

# ----------------- HELPERS -----------------
def get_full_timestamp():
    return datetime.now(IST).strftime("%d-%m-%Y %I:%M %p")

def is_admin_or_owner(user_id):
    return user_id in db.get("admins", []) or user_id == OWNER_ID

def is_group_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception:
        return False

def register_user(user, chat_id=None):
    user_id = str(user.id)
    is_new = user_id not in db.get("users", {})

    if is_new:
        db.setdefault("users", {})[user_id] = {
            "id": user.id,
            "name": user.first_name or "Unknown",
            "username": f"@{user.username}" if user.username else "No Username",
            "joined_at": get_full_timestamp()
        }
        save_db(db)

        if db.get("settings", {}).get("new_user_notify", True):
            u_tag = f"@{user.username}" if user.username else "None"
            alert_text = (
                "New User Alert:\n\n"
                f"Name: {user.first_name}\n"
                f"User ID: <code>{user.id}</code>\n"
                f"Username: {u_tag}\n"
                f"Date: <code>{get_full_timestamp()}</code>"
            )
            for adm in db.get("admins", []):
                try:
                    bot.send_message(adm, alert_text)
                except Exception:
                    pass
    else:
        db["users"][user_id]["name"] = user.first_name or "Unknown"
        db["users"][user_id]["username"] = f"@{user.username}" if user.username else "No Username"
        save_db(db)

def get_admin_panel_markup():
    m_status = "ON" if db.get("settings", {}).get("maintenance", False) else "OFF"
    n_status = "ON" if db.get("settings", {}).get("new_user_notify", True) else "OFF"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Mailing", callback_data="adm_mailing_select"),
        types.InlineKeyboardButton("Statistics", callback_data="adm_stats"),
        types.InlineKeyboardButton(f"Maint. ({m_status})", callback_data="toggle_maintenance"),
        types.InlineKeyboardButton(f"New User ({n_status})", callback_data="toggle_notify"),
        types.InlineKeyboardButton("Banned Words", callback_data="adm_banned_words"),
        types.InlineKeyboardButton("Custom Replies", callback_data="adm_custom_replies"),
        types.InlineKeyboardButton("Manage Admins", callback_data="adm_manage_list"),
        types.InlineKeyboardButton("Close Panel", callback_data="adm_close")
    )
    return markup

# ----------------- ANTI-BOT ADD PROTECTION -----------------
@bot.message_handler(content_types=['new_chat_members'])
def handle_bot_addition(message):
    chat_id = message.chat.id
    adder_id = message.from_user.id
    is_adder_adm = is_group_admin(chat_id, adder_id)

    for member in message.new_chat_members:
        if member.is_bot and member.id != bot.get_me().id:
            if not is_adder_adm:
                try:
                    bot.ban_chat_member(chat_id, member.id)
                    bot.delete_message(chat_id, message.message_id)
                except Exception:
                    pass

# ----------------- PRIVATE COMMANDS -----------------
@bot.message_handler(commands=['start'], chat_types=['private'])
def handle_start(message):
    user = message.from_user
    register_user(user, message.chat.id)

    parts = message.text.split()
    if len(parts) > 1 and parts[1].startswith("appeal_"):
        cid = parts[1].replace("appeal_", "")
        admin_state[user.id] = f"user_appeal_{cid}"
        bot.reply_to(message, "Ban/Mute Appeal Portal:\n\nType your explanation message below:")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Submit Appeal", callback_data="u_appeal_menu"),
        types.InlineKeyboardButton("Report User", callback_data="u_report_menu")
    )
    bot.reply_to(message, f"Welcome {user.first_name} to the Group Support Desk.\nSelect an option:", reply_markup=markup)

@bot.message_handler(commands=['claim'], chat_types=['private'])
def handle_claim_command(message):
    user_id = message.from_user.id
    if is_admin_or_owner(user_id):
        bot.reply_to(message, "You are already authorized as an Admin. Send <code>/admin</code> to open dashboard.")
        return

    admin_state[user_id] = "waiting_claim_password"
    bot.reply_to(message, "Secret Access Verification Required:\n\nPlease enter the secret admin key to claim access:")

@bot.message_handler(commands=['admin'], chat_types=['private'])
def handle_admin_command(message):
    if not is_admin_or_owner(message.from_user.id):
        bot.reply_to(message, "Access Denied. Send <code>/claim</code> to authenticate first.")
        return
    bot.reply_to(message, "Administrator Control Panel\nSelect an action from the options below:", reply_markup=get_admin_panel_markup())

# ----------------- GROUP MANUAL COMMANDS -----------------
@bot.message_handler(commands=['warn'], chat_types=['group', 'supergroup'])
def cmd_warn(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    if not message.reply_to_message:
        bot.reply_to(message, "Reply to a user's message to warn them.")
        return

    target = message.reply_to_message.from_user
    key = f"{target.id}_{chat.id}"
    curr_warns = db.get("warnings", {}).get(key, 0) + 1
    db.setdefault("warnings", {})[key] = curr_warns
    save_db(db)

    uname = f"@{target.username}" if target.username else target.first_name

    if curr_warns < 3:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{target.id}_{chat.id}"))
        bot.send_message(chat.id, f"{uname} [{target.id}] warned ({curr_warns} of 3).", reply_markup=markup)
    else:
        db["warnings"].pop(key, None)
        save_db(db)
        try:
            bot.ban_chat_member(chat.id, target.id)
        except Exception:
            pass

        bot_user = bot.get_me().username
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal_{chat.id}"),
            types.InlineKeyboardButton("Unban", callback_data=f"act_unban_{target.id}_{chat.id}")
        )
        bot.send_message(chat.id, f"{uname} [{target.id}] banned.", reply_markup=markup)

@bot.message_handler(commands=['mute'], chat_types=['group', 'supergroup'])
def cmd_mute(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    if not message.reply_to_message:
        bot.reply_to(message, "Reply to a user's message to mute them.")
        return

    target = message.reply_to_message.from_user
    uname = f"@{target.username}" if target.username else target.first_name

    try:
        bot.restrict_chat_member(chat.id, target.id, can_send_messages=False)
        bot_user = bot.get_me().username
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal_{chat.id}"),
            types.InlineKeyboardButton("Unmute", callback_data=f"act_unmute_{target.id}_{chat.id}")
        )
        bot.send_message(chat.id, f"{uname} [{target.id}] has been muted.", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['ban'], chat_types=['group', 'supergroup'])
def cmd_ban(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    if not message.reply_to_message:
        bot.reply_to(message, "Reply to a user's message to ban them.")
        return

    target = message.reply_to_message.from_user
    uname = f"@{target.username}" if target.username else target.first_name

    try:
        bot.ban_chat_member(chat.id, target.id)
        bot_user = bot.get_me().username
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal_{chat.id}"),
            types.InlineKeyboardButton("Unban", callback_data=f"act_unban_{target.id}_{chat.id}")
        )
        bot.send_message(chat.id, f"{uname} [{target.id}] banned.", reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ----------------- GROUP MODERATION & ANTI-SPAM -----------------
@bot.message_handler(chat_types=['group', 'supergroup'], content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_group_moderation(message):
    user = message.from_user
    chat = message.chat
    text = message.text or message.caption or ""

    if not user or user.is_bot:
        return

    if str(chat.id) not in db.get("groups", {}):
        db.setdefault("groups", {})[str(chat.id)] = {"id": chat.id, "title": chat.title}
        save_db(db)

    is_user_adm = is_group_admin(chat.id, user.id)

    # 1. Custom Triggers
    if text:
        custom_dict = db.get("custom_replies", {})
        for trigger, cdata in custom_dict.items():
            if trigger in text.lower():
                markup = types.InlineKeyboardMarkup()
                if cdata.get("btn_name") and cdata.get("btn_url"):
                    markup.add(types.InlineKeyboardButton(cdata["btn_name"], url=cdata["btn_url"]))
                bot.reply_to(message, cdata["reply_text"], reply_markup=markup if cdata.get("btn_name") else None)
                break

    if is_user_adm:
        return

    # 2. Anti-Link Filter
    url_pattern = r"(https?://\S+|www\.\S+|t\.me/\S+)"
    if re.search(url_pattern, text):
        try:
            bot.delete_message(chat.id, message.message_id)
            return
        except Exception:
            pass

    # 3. Banned Words Filter
    for word in db.get("banned_words", []):
        if word in text.lower():
            try:
                bot.delete_message(chat.id, message.message_id)
                return
            except Exception:
                pass

    # 4. Anti-Flood System (10s window, max 3 messages)
    now = time.time()
    user_history = user_message_history.setdefault(user.id, [])
    user_history.append(now)
    user_message_history[user.id] = [t for t in user_history if now - t <= 10]

    if len(user_message_history[user.id]) > 3:
        try:
            bot.delete_message(chat.id, message.message_id)
        except Exception:
            pass

        key = f"{user.id}_{chat.id}"
        curr_warns = db.get("warnings", {}).get(key, 0) + 1
        db.setdefault("warnings", {})[key] = curr_warns
        save_db(db)

        uname = f"@{user.username}" if user.username else user.first_name

        if curr_warns < 3:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{user.id}_{chat.id}"))
            bot.send_message(chat.id, f"{uname} [{user.id}] warned ({curr_warns} of 3).", reply_markup=markup)
        else:
            db["warnings"].pop(key, None)
            save_db(db)
            try:
                bot.ban_chat_member(chat.id, user.id)
            except Exception:
                pass

            bot_user = bot.get_me().username
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal_{chat.id}"),
                types.InlineKeyboardButton("Unban", callback_data=f"act_unban_{user.id}_{chat.id}")
            )
            bot.send_message(chat.id, f"{uname} [{user.id}] banned.", reply_markup=markup)

# ----------------- PRIVATE DIALOGUE / CLAIM INPUT HANDLER -----------------
@bot.message_handler(chat_types=['private'], content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_private_dialogue(message):
    user_id = message.from_user.id
    state = admin_state.get(user_id)
    text = message.text or ""

    if not state:
        return

    if state == "waiting_claim_password":
        admin_state.pop(user_id, None)
        entered_pass = text.strip()

        if entered_pass == ADMIN_SECRET_KEY:
            if user_id not in db.setdefault("admins", []):
                db["admins"].append(user_id)
                save_db(db)
            bot.reply_to(
                message,
                "Admin Password Verified.\nYou are now authorized as Master Admin. Use <code>/admin</code> to open dashboard.",
                reply_markup=get_admin_panel_markup()
            )
        else:
            bot.reply_to(message, "Incorrect Password. Access Denied.")
        return

    if state.startswith("user_appeal_"):
        cid = state.replace("user_appeal_", "")
        admin_state.pop(user_id, None)
        alert = (
            "New Appeal Submitted:\n\n"
            f"User: {message.from_user.first_name} (@{message.from_user.username}) [ID: <code>{user_id}</code>]\n"
            f"Group ID: <code>{cid}</code>\n\n"
            f"Appeal Note:\n{text}"
        )
        for adm in db.get("admins", []):
            try:
                bot.send_message(adm, alert)
            except Exception:
                pass
        bot.reply_to(message, "Your appeal has been received and forwarded to group admins.")
        return

    if state == "add_banned_word":
        admin_state.pop(user_id, None)
        w = text.lower().strip()
        if w and w not in db.get("banned_words", []):
            db.setdefault("banned_words", []).append(w)
            save_db(db)
        bot.reply_to(message, f"Word '{w}' added to banned words blacklist.", reply_markup=get_admin_panel_markup())
        return

    if state == "cr_step1_trigger":
        admin_state[user_id] = f"cr_step2_text_{text.lower().strip()}"
        bot.reply_to(message, f"Trigger set to '{text.lower().strip()}'.\n\nStep 2: Send the reply text:")
        return

    if state.startswith("cr_step2_text_"):
        trigger = state.replace("cr_step2_text_", "")
        admin_state[user_id] = f"cr_step3_btn_{trigger}__SPLIT__{text}"
        bot.reply_to(message, "Step 3: To attach an inline button, send: <code>Button Name | https://link.com</code>\nOr type <code>skip</code> for text-only reply.")
        return

    if state.startswith("cr_step3_btn_"):
        raw_payload = state.replace("cr_step3_btn_", "")
        trigger, reply_txt = raw_payload.split("__SPLIT__")
        admin_state.pop(user_id, None)

        btn_name, btn_url = None, None
        if text.lower() != "skip" and "|" in text:
            p = text.split("|")
            btn_name = p[0].strip()
            btn_url = p[1].strip()

        db.setdefault("custom_replies", {})[trigger] = {
            "reply_text": reply_txt,
            "btn_name": btn_name,
            "btn_url": btn_url
        }
        save_db(db)
        bot.reply_to(message, "Custom auto-reply configured successfully.", reply_markup=get_admin_panel_markup())
        return

    if state.startswith("broadcast_"):
        target_mode = state.replace("broadcast_", "")
        admin_state.pop(user_id, None)
        status_msg = bot.reply_to(message, "Broadcasting...")

        targets = []
        if target_mode in ["users", "both"]:
            targets.extend(list(db.get("users", {}).keys()))
        if target_mode in ["groups", "both"]:
            targets.extend(list(db.get("groups", {}).keys()))

        sent, failed = 0, 0
        for tid in set(targets):
            try:
                bot.copy_message(chat_id=int(tid), from_chat_id=message.chat.id, message_id=message.message_id)
                sent += 1
                time.sleep(0.04)
            except Exception:
                failed += 1

        report = (
            f"Broadcast Completed ({target_mode.upper()}):\n\n"
            f"• Delivered: <code>{sent}</code>\n"
            f"• Failed: <code>{failed}</code>"
        )
        bot.edit_message_text(report, chat_id=message.chat.id, message_id=status_msg.message_id)
        return

# ----------------- CALLBACK QUERY HANDLER -----------------
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    if data.startswith("warn_opt_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            bot.answer_callback_query(call.id, "Admin only action.", show_alert=True)
            return

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("+1", callback_data=f"w_add_{target_uid}_{target_cid}"),
            types.InlineKeyboardButton("-1", callback_data=f"w_sub_{target_uid}_{target_cid}")
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data.startswith("w_add_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            return
        key = f"{target_uid}_{target_cid}"
        count = db.get("warnings", {}).get(key, 0) + 1
        db.setdefault("warnings", {})[key] = count
        save_db(db)
        bot.edit_message_text(f"Updated: User [{target_uid}] warnings ({count} of 3).", call.message.chat.id, call.message.message_id)
        return

    if data.startswith("w_sub_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            return
        key = f"{target_uid}_{target_cid}"
        count = max(0, db.get("warnings", {}).get(key, 0) - 1)
        db.setdefault("warnings", {})[key] = count
        save_db(db)
        bot.edit_message_text(f"Updated: User [{target_uid}] warnings ({count} of 3).", call.message.chat.id, call.message.message_id)
        return

    if data.startswith("act_unban_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            bot.answer_callback_query(call.id, "Admin only action.", show_alert=True)
            return
        try:
            bot.unban_chat_member(int(target_cid), int(target_uid), only_if_banned=True)
            bot.edit_message_text(f"User [{target_uid}] unbanned by {call.from_user.first_name}.", call.message.chat.id, call.message.message_id)
        except Exception as e:
            bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)
        return

    if data.startswith("act_unmute_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            bot.answer_callback_query(call.id, "Admin only action.", show_alert=True)
            return
        try:
            bot.restrict_chat_member(
                int(target_cid), int(target_uid),
                can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True
            )
            bot.edit_message_text(f"User [{target_uid}] unmuted by {call.from_user.first_name}.", call.message.chat.id, call.message.message_id)
        except Exception as e:
            bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)
        return

    if not is_admin_or_owner(user_id):
        bot.answer_callback_query(call.id, "Access Denied.")
        return

    if data == "adm_close":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        return

    if data == "adm_stats":
        u_len = len(db.get("users", {}))
        g_len = len(db.get("groups", {}))
        w_len = len(db.get("banned_words", []))
        c_len = len(db.get("custom_replies", {}))
        stats_text = (
            "Bot Real-time Analytics:\n\n"
            f"• Registered Users: <code>{u_len}</code>\n"
            f"• Active Groups: <code>{g_len}</code>\n"
            f"• Banned Words: <code>{w_len}</code>\n"
            f"• Custom Replies: <code>{c_len}</code>\n"
            f"• Storage: <code>Neon Postgres JSONB (Lifetime)</code>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_mailing_select":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("Both (Users + Groups)", callback_data="mail_both"),
            types.InlineKeyboardButton("Users Only", callback_data="mail_users"),
            types.InlineKeyboardButton("Groups Only", callback_data="mail_groups"),
            types.InlineKeyboardButton("Back to Dashboard", callback_data="adm_back")
        )
        bot.edit_message_text("Select Mailing Target:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data.startswith("mail_"):
        target_mode = data.replace("mail_", "")
        admin_state[user_id] = f"broadcast_{target_mode}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_back"))
        bot.edit_message_text(f"Broadcast Mode ({target_mode.upper()}):\n\nSend or forward the message you want to broadcast:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_banned_words":
        words = ", ".join(db.get("banned_words", [])) or "None"
        admin_state[user_id] = "add_banned_word"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text(f"Current Banned Words:\n{words}\n\nSend the word/phrase you want to blacklist:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_custom_replies":
        admin_state[user_id] = "cr_step1_trigger"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text("Custom Auto-Reply Setup:\n\nStep 1: Send the trigger keyword:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "toggle_maintenance":
        curr = db.setdefault("settings", {}).get("maintenance", False)
        db["settings"]["maintenance"] = not curr
        save_db(db)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data == "toggle_notify":
        curr = db.setdefault("settings", {}).get("new_user_notify", True)
        db["settings"]["new_user_notify"] = not curr
        save_db(db)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        return

    if data == "adm_manage_list":
        adms = db.get("admins", [])
        lines = [f"• <code>{a}</code>" for a in adms]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text("Authorized Admins:\n\n" + "\n".join(lines), call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_back":
        admin_state.pop(user_id, None)
        bot.edit_message_text("Administrator Control Panel\nSelect an action from the options below:", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        return

# ----------------- MAIN RUNNER -----------------
def run_bot_polling():
    while True:
        try:
            print("[BOT] Starting Telegram polling cleanly...", flush=True)
            bot.remove_webhook()
            time.sleep(2)
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"[BOT ERROR] Polling interrupted: {e}. Retrying in 5s...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    run_bot_polling()
