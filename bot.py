import os
import sys
import time
import json
import re
import random
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types
from datetime import datetime, timezone, timedelta
import psycopg

sys.stdout.reconfigure(line_buffering=True)

# ----------------- CONFIGURATION -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
ADMIN_SECRET_KEY = "mansour$vx"

if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN missing in environment variables!", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", disable_web_page_preview=True)

# ----------------- 24/7 WEB SERVER FOR RENDER / UPTIMEROBOT -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Moderation Bot is Live on Neon Postgres")

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
        print(f"[SERVER ERROR] {e}", flush=True)

threading.Thread(target=run_server, daemon=True).start()

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
        print("[DATABASE] PostgreSQL storage ready.", flush=True)
    except Exception as e:
        print(f"[DATABASE ERROR] Init failed: {e}", flush=True)

def get_default_db_data():
    return {
        "_id": "mod_config",
        "admins": [OWNER_ID] if OWNER_ID else [],
        "users": {},
        "groups": {},
        "warnings": {},
        "banned_words": ["gali", "madarchod", "bhenchod", "bhosdike", "chutiya", "randi"],
        "custom_replies": {},
        "appeals": {},
        "media": {
            "start": None,
            "ban": None,
            "mute": None,
            "warn": None
        },
        "settings": {
            "maintenance": False,
            "new_user_notify": True
        }
    }

def save_db(data):
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

def load_db():
    default_data = get_default_db_data()
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
                    if "media" not in data:
                        data["media"] = default_data["media"]
                    if OWNER_ID and OWNER_ID not in data.get("admins", []):
                        data.setdefault("admins", []).append(OWNER_ID)
                    return data
                else:
                    save_db(default_data)
                    return default_data
    except Exception as e:
        print(f"[DATABASE ERROR] Load failed: {e}", flush=True)
        return default_data

threading.Thread(target=init_postgres, daemon=True).start()
db = load_db()

# In-Memory Cache
admin_state = {}
user_message_history = {}
user_warn_cache = {}
IST = timezone(timedelta(hours=5, minutes=30))

# ----------------- TELEGRAM COMMAND MENU REGISTRATION -----------------
def setup_bot_commands():
    try:
        cmd_list = [
            types.BotCommand("start", "Start the support bot"),
            types.BotCommand("help", "View available group commands"),
            types.BotCommand("info", "View user moderation info"),
            types.BotCommand("warn", "Warn a user (Admin only)"),
            types.BotCommand("unwarn", "Remove user warning (Admin only)"),
            types.BotCommand("mute", "Mute a user (Admin only)"),
            types.BotCommand("unmute", "Unmute a user (Admin only)"),
            types.BotCommand("ban", "Ban a user (Admin only)"),
            types.BotCommand("unban", "Unban a user (Admin only)"),
            types.BotCommand("admin", "Open Administrator Panel"),
            types.BotCommand("claim", "Claim admin authorization")
        ]
        bot.set_my_commands(cmd_list)
        print("[BOT] Bot command suggestion menu registered successfully.", flush=True)
    except Exception as e:
        print(f"[BOT] Command setup failed: {e}", flush=True)

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
                "<b>New User Alert:</b>\n\n"
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

def get_target_user(message):
    if message.reply_to_message:
        return message.reply_to_message.from_user
    args = message.text.split()
    if len(args) > 1:
        target_str = args[1].replace("@", "")
        if target_str.isdigit():
            try:
                chat_member = bot.get_chat_member(message.chat.id, int(target_str))
                return chat_member.user
            except Exception:
                return types.User(int(target_str), False, "User")
        for u in db.get("users", {}).values():
            if u.get("username", "").lower().replace("@", "") == target_str.lower():
                return types.User(u["id"], False, u["name"], username=target_str)
    return None

def send_with_optional_media(chat_id, media_key, text, reply_markup=None):
    media_id = db.get("media", {}).get(media_key)
    if media_id:
        try:
            bot.send_photo(chat_id, media_id, caption=text, reply_markup=reply_markup)
            return
        except Exception:
            try:
                bot.send_video(chat_id, media_id, caption=text, reply_markup=reply_markup)
                return
            except Exception:
                try:
                    bot.send_animation(chat_id, media_id, caption=text, reply_markup=reply_markup)
                    return
                except Exception:
                    pass
    bot.send_message(chat_id, text, reply_markup=reply_markup)

# ----------------- UI MARKUPS -----------------
def get_user_main_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Submit Appeal", callback_data="u_appeal_menu"),
        types.InlineKeyboardButton("Report User", callback_data="u_report_menu"),
        types.InlineKeyboardButton("My Status", callback_data="u_status_menu")
    )
    return markup

def get_appeal_target_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Sell Hub", callback_data="appeal_target_sellhub"),
        types.InlineKeyboardButton("Comchater", callback_data="appeal_target_comchater"),
        types.InlineKeyboardButton("Cancel", callback_data="u_main_menu")
    )
    return markup

def get_admin_panel_markup():
    m_status = "ON" if db.get("settings", {}).get("maintenance", False) else "OFF"
    n_status = "ON" if db.get("settings", {}).get("new_user_notify", True) else "OFF"

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Mailing", callback_data="adm_mailing_select"),
        types.InlineKeyboardButton("Statistics", callback_data="adm_stats"),
        types.InlineKeyboardButton("Manage Media", callback_data="adm_media_menu"),
        types.InlineKeyboardButton("Banned Words", callback_data="adm_banned_words"),
        types.InlineKeyboardButton(f"Maint. ({m_status})", callback_data="toggle_maintenance"),
        types.InlineKeyboardButton(f"New User ({n_status})", callback_data="toggle_notify"),
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

    welcome_text = (
        f"<b>Welcome, {user.first_name}</b>\n\n"
        "This is the official Group Support & Appeal Portal.\n"
        "Please choose an option below to proceed:"
    )
    send_with_optional_media(message.chat.id, "start", welcome_text, get_user_main_markup())

@bot.message_handler(commands=['help'])
def handle_help_command(message):
    help_text = (
        "<b>Available Bot Commands:</b>\n\n"
        "<b>General Commands:</b>\n"
        "• <code>/start</code> - Open Private Support Portal\n"
        "• <code>/info</code> - View user warning status\n"
        "• <code>/help</code> - Show this commands guide\n\n"
        "<b>Admin Commands (Group):</b>\n"
        "• <code>/warn [reply/user]</code> - Issue warning\n"
        "• <code>/unwarn [reply/user]</code> - Remove warning\n"
        "• <code>/mute [reply/user]</code> - Mute user\n"
        "• <code>/unmute [reply/user]</code> - Unmute user\n"
        "• <code>/ban [reply/user]</code> - Ban user\n"
        "• <code>/unban [reply/user]</code> - Unban user\n\n"
        "<b>Admin Commands (Private):</b>\n"
        "• <code>/admin</code> - Open Control Dashboard\n"
        "• <code>/claim</code> - Verify secret admin password"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['claim'], chat_types=['private'])
def handle_claim_command(message):
    user_id = message.from_user.id
    if is_admin_or_owner(user_id):
        bot.reply_to(message, "You are already authorized as an Admin. Use <code>/admin</code> to access panel.")
        return

    admin_state[user_id] = "waiting_claim_password"
    bot.reply_to(message, "<b>Authentication Required:</b>\nPlease enter the secret admin access key:")

@bot.message_handler(commands=['admin'], chat_types=['private'])
def handle_admin_command(message):
    if not is_admin_or_owner(message.from_user.id):
        bot.reply_to(message, "Access Denied. Use <code>/claim</code> to authenticate first.")
        return
    bot.reply_to(message, "<b>Administrator Control Panel</b>\nChoose a category below to manage settings:", reply_markup=get_admin_panel_markup())

# ----------------- GROUP MODERATION COMMANDS -----------------
@bot.message_handler(commands=['warn'], chat_types=['group', 'supergroup'])
def cmd_warn(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/warn username/id</code>")
        return

    key = f"{target.id}_{chat.id}"
    curr_warns = db.get("warnings", {}).get(key, 0) + 1
    db.setdefault("warnings", {})[key] = curr_warns
    user_warn_cache[key] = curr_warns
    save_db(db)

    uname = f"@{target.username}" if target.username else target.first_name

    if curr_warns < 3:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{target.id}_{chat.id}"))
        warn_msg = f"{uname} [{target.id}] warned ({curr_warns} of 3)."
        send_with_optional_media(chat.id, "warn", warn_msg, markup)
    else:
        db["warnings"].pop(key, None)
        user_warn_cache.pop(key, None)
        save_db(db)
        try:
            bot.restrict_chat_member(chat.id, target.id, can_send_messages=False)
        except Exception:
            pass

        bot_user = bot.get_me().username
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal"),
            types.InlineKeyboardButton("Unmute", callback_data=f"act_unmute_{target.id}_{chat.id}")
        )
        mute_msg = f"{uname} [{target.id}] has been muted (3 Warnings Reached)."
        send_with_optional_media(chat.id, "mute", mute_msg, markup)

@bot.message_handler(commands=['unwarn'], chat_types=['group', 'supergroup'])
def cmd_unwarn(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/unwarn username/id</code>")
        return

    key = f"{target.id}_{chat.id}"
    curr_warns = max(0, db.get("warnings", {}).get(key, 0) - 1)
    db.setdefault("warnings", {})[key] = curr_warns
    user_warn_cache[key] = curr_warns
    save_db(db)

    uname = f"@{target.username}" if target.username else target.first_name
    bot.send_message(chat.id, f"Warning removed for {uname} [{target.id}]. Current warnings: ({curr_warns} of 3).")

@bot.message_handler(commands=['mute'], chat_types=['group', 'supergroup'])
def cmd_mute(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/mute username/id</code>")
        return

    uname = f"@{target.username}" if target.username else target.first_name
    try:
        bot.restrict_chat_member(chat.id, target.id, can_send_messages=False)
        bot_user = bot.get_me().username
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal"),
            types.InlineKeyboardButton("Unmute", callback_data=f"act_unmute_{target.id}_{chat.id}")
        )
        mute_msg = f"{uname} [{target.id}] has been muted by Admin."
        send_with_optional_media(chat.id, "mute", mute_msg, markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['unmute'], chat_types=['group', 'supergroup'])
def cmd_unmute(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/unmute username/id</code>")
        return

    uname = f"@{target.username}" if target.username else target.first_name
    try:
        bot.restrict_chat_member(
            chat.id, target.id,
            can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True
        )
        bot.send_message(chat.id, f"{uname} [{target.id}] has been unmuted.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['ban'], chat_types=['group', 'supergroup'])
def cmd_ban(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/ban username/id</code>")
        return

    uname = f"@{target.username}" if target.username else target.first_name
    try:
        bot.ban_chat_member(chat.id, target.id)
        
        # Send Private DM only on BAN
        bot_user = bot.get_me().username
        ban_dm_text = (
            f"Hello,\n\nYou have been <b>banned</b> from <b>{chat.title}</b>.\n"
            "If you consider this an error, you can submit an appeal using the portal below."
        )
        dm_markup = types.InlineKeyboardMarkup()
        dm_markup.add(types.InlineKeyboardButton("Submit Appeal", url=f"https://t.me/{bot_user}?start=appeal"))
        try:
            bot.send_message(target.id, ban_dm_text, reply_markup=dm_markup)
        except Exception:
            pass

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Unban", callback_data=f"act_unban_{target.id}_{chat.id}"))
        ban_msg = f"{uname} [{target.id}] banned by Admin."
        send_with_optional_media(chat.id, "ban", ban_msg, markup)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['unban'], chat_types=['group', 'supergroup'])
def cmd_unban(message):
    chat = message.chat
    if not is_group_admin(chat.id, message.from_user.id):
        return

    target = get_target_user(message)
    if not target:
        bot.reply_to(message, "Usage: Reply to a user's message or send <code>/unban username/id</code>")
        return

    uname = f"@{target.username}" if target.username else target.first_name
    try:
        bot.unban_chat_member(chat.id, target.id, only_if_banned=True)
        bot.send_message(chat.id, f"{uname} [{target.id}] has been unbanned.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['info'])
def cmd_info(message):
    target = get_target_user(message) or message.from_user
    chat_id = message.chat.id
    key = f"{target.id}_{chat_id}"
    warn_count = db.get("warnings", {}).get(key, 0)
    u_info = db.get("users", {}).get(str(target.id), {})
    joined = u_info.get("joined_at", "N/A")

    info_text = (
        "<b>User Record:</b>\n\n"
        f"• Name: {target.first_name}\n"
        f"• User ID: <code>{target.id}</code>\n"
        f"• Username: @{target.username if target.username else 'None'}\n"
        f"• Warnings in this chat: <code>{warn_count}/3</code>\n"
        f"• First Seen: <code>{joined}</code>"
    )
    bot.reply_to(message, info_text)

# ----------------- HIGH SPEED GROUP MODERATION -----------------
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

    # 4. Fast Anti-Flood: 4th Message Deleted Instantly
    now = time.time()
    user_history = user_message_history.setdefault(user.id, [])
    user_history.append(now)
    user_message_history[user.id] = [t for t in user_history if now - t <= 10]

    if len(user_message_history[user.id]) >= 4:
        try:
            bot.delete_message(chat.id, message.message_id)
        except Exception:
            pass

        key = f"{user.id}_{chat.id}"
        curr_warns = user_warn_cache.get(key, db.get("warnings", {}).get(key, 0)) + 1
        user_warn_cache[key] = curr_warns
        db.setdefault("warnings", {})[key] = curr_warns
        save_db(db)

        user_message_history[user.id] = []
        uname = f"@{user.username}" if user.username else user.first_name

        if curr_warns < 3:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{user.id}_{chat.id}"))
            warn_msg = f"{uname} [{user.id}] warned ({curr_warns} of 3)."
            send_with_optional_media(chat.id, "warn", warn_msg, markup)
        else:
            db["warnings"].pop(key, None)
            user_warn_cache.pop(key, None)
            save_db(db)
            try:
                bot.restrict_chat_member(chat.id, user.id, can_send_messages=False)
            except Exception:
                pass

            bot_user = bot.get_me().username
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Appeal", url=f"https://t.me/{bot_user}?start=appeal"),
                types.InlineKeyboardButton("Unmute", callback_data=f"act_unmute_{user.id}_{chat.id}")
            )
            mute_msg = f"{uname} [{user.id}] has been muted (3 Warnings Reached)."
            send_with_optional_media(chat.id, "mute", mute_msg, markup)

# ----------------- PRIVATE CONVERSATION & FORM INPUTS -----------------
@bot.message_handler(chat_types=['private'], content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_private_dialogue(message):
    user_id = message.from_user.id
    state = admin_state.get(user_id)
    text = message.text or ""

    if not state:
        return

    # Admin Password Claim
    if state == "waiting_claim_password":
        admin_state.pop(user_id, None)
        if text.strip() == ADMIN_SECRET_KEY:
            if user_id not in db.setdefault("admins", []):
                db["admins"].append(user_id)
                save_db(db)
            bot.reply_to(
                message,
                "<b>Authentication Successful:</b>\nYou are now recognized as a Master Administrator. Use <code>/admin</code> to open control dashboard.",
                reply_markup=get_admin_panel_markup()
            )
        else:
            bot.reply_to(message, "Incorrect authorization key.")
        return

    # Appeal Text Validation (50 chars to 150 words + No Abusive Words)
    if state.startswith("submitting_appeal_"):
        target_channel = state.replace("submitting_appeal_", "")
        
        # 1. Abusive word check
        for bw in db.get("banned_words", []):
            if bw in text.lower():
                bot.reply_to(
                    message,
                    "<b>Appeal Rejected:</b>\nAbusive language or profanity is strictly prohibited in appeal submissions. Please compose your appeal respectfully and send again:"
                )
                return

        # 2. Length check
        words_count = len(text.split())
        char_count = len(text.strip())

        if char_count < 50:
            bot.reply_to(
                message,
                f"<b>Appeal Too Short:</b>\nYour appeal contains only {char_count} characters. Please provide a clear explanation between 50 characters and 150 words."
            )
            return

        if words_count > 150:
            bot.reply_to(
                message,
                f"<b>Appeal Exceeds Word Limit:</b>\nYour appeal contains {words_count} words (Maximum allowed: 150 words). Please make it concise and send again."
            )
            return

        admin_state.pop(user_id, None)
        appeal_id = str(int(time.time()))
        db.setdefault("appeals", {})[appeal_id] = {
            "user_id": user_id,
            "target": target_channel,
            "name": message.from_user.first_name,
            "username": message.from_user.username,
            "text": text,
            "status": "Pending",
            "time": get_full_timestamp()
        }
        save_db(db)

        # Notify Admins
        adm_note = (
            f"<b>New Appeal Received [ID: #{appeal_id}]</b>\n\n"
            f"• Target: <b>{target_channel}</b>\n"
            f"• User: {message.from_user.first_name} (@{message.from_user.username}) [<code>{user_id}</code>]\n"
            f"• Date: <code>{get_full_timestamp()}</code>\n\n"
            f"<b>Statement:</b>\n{text}"
        )
        for adm in db.get("admins", []):
            try:
                bot.send_message(adm, adm_note)
            except Exception:
                pass

        bot.reply_to(message, "<b>Appeal Submitted:</b>\nYour appeal request has been recorded and submitted to the review board. You can check the status anytime under 'My Status'.")
        return

    # Report Submission
    if state == "submitting_report":
        admin_state.pop(user_id, None)
        alert = (
            "<b>User Incident Report:</b>\n\n"
            f"• Submitter: {message.from_user.first_name} [<code>{user_id}</code>]\n"
            f"• Date: <code>{get_full_timestamp()}</code>\n\n"
            f"<b>Report Details:</b>\n{text}"
        )
        for adm in db.get("admins", []):
            try:
                bot.send_message(adm, alert)
            except Exception:
                pass
        bot.reply_to(message, "Thank you. Your report has been submitted to the moderation desk.")
        return

    # Add Banned Word
    if state == "adm_add_banned_word":
        admin_state.pop(user_id, None)
        new_w = text.lower().strip()
        if new_w and new_w not in db.get("banned_words", []):
            db.setdefault("banned_words", []).append(new_w)
            save_db(db)
            bot.reply_to(message, f"Word '<code>{new_w}</code>' has been added to blacklist.", reply_markup=get_admin_panel_markup())
        else:
            bot.reply_to(message, "Word already in list or invalid.", reply_markup=get_admin_panel_markup())
        return

    # Media File Management
    if state.startswith("media_set_"):
        media_type = state.replace("media_set_", "")
        file_id = None
        if message.photo:
            file_id = message.photo[-1].file_id
        elif message.video:
            file_id = message.video.file_id
        elif message.animation:
            file_id = message.animation.file_id

        admin_state.pop(user_id, None)
        if file_id:
            db.setdefault("media", {})[media_type] = file_id
            save_db(db)
            bot.reply_to(message, f"Media for <b>{media_type.upper()}</b> updated successfully.", reply_markup=get_admin_panel_markup())
        else:
            bot.reply_to(message, "No valid photo, video or GIF detected. Action cancelled.", reply_markup=get_admin_panel_markup())
        return

    # Custom Reply Creation Flow
    if state == "cr_step1_trigger":
        admin_state[user_id] = f"cr_step2_text_{text.lower().strip()}"
        bot.reply_to(message, f"Trigger set: <code>{text.lower().strip()}</code>\n\nStep 2: Send the response text:")
        return

    if state.startswith("cr_step2_text_"):
        trigger = state.replace("cr_step2_text_", "")
        admin_state[user_id] = f"cr_step3_btn_{trigger}__SPLIT__{text}"
        bot.reply_to(message, "Step 3: To attach a button, format as: <code>Button Title | https://link.com</code>\nOr type <code>skip</code> for text only.")
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
        bot.reply_to(message, "Custom auto-reply saved successfully.", reply_markup=get_admin_panel_markup())
        return

    # Broadcast Flow
    if state.startswith("broadcast_"):
        target_mode = state.replace("broadcast_", "")
        admin_state.pop(user_id, None)
        status_msg = bot.reply_to(message, "Broadcasting in progress...")

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
            f"<b>Broadcast Report ({target_mode.upper()}):</b>\n\n"
            f"• Delivered: <code>{sent}</code>\n"
            f"• Failed: <code>{failed}</code>"
        )
        bot.edit_message_text(report, chat_id=message.chat.id, message_id=status_msg.message_id)
        return

# ----------------- CALLBACK QUERY ROUTER -----------------
@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    # User Navigation
    if data == "u_main_menu":
        admin_state.pop(user_id, None)
        welcome_text = (
            f"<b>Welcome, {call.from_user.first_name}</b>\n\n"
            "This is the official Group Support & Appeal Portal.\n"
            "Please choose an option below to proceed:"
        )
        bot.edit_message_text(welcome_text, call.message.chat.id, call.message.message_id, reply_markup=get_user_main_markup())
        return

    if data == "u_appeal_menu":
        bot.edit_message_text(
            "<b>Appeal Submission Portal:</b>\n\nPlease select the community group where you are appealing your restriction:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_appeal_target_markup()
        )
        return

    if data.startswith("appeal_target_"):
        target = "Sell Hub" if "sellhub" in data else "Comchater"
        admin_state[user_id] = f"submitting_appeal_{target}"
        prompt = (
            f"<b>Appeal Submission for {target}:</b>\n\n"
            "Please write your statement explaining why the restriction should be lifted.\n\n"
            "<b>Requirements:</b>\n"
            "• Length: Minimum 50 characters, Maximum 150 words.\n"
            "• Profanity or abusive words are strictly prohibited."
        )
        bot.edit_message_text(prompt, call.message.chat.id, call.message.message_id)
        return

    if data == "u_report_menu":
        admin_state[user_id] = "submitting_report"
        bot.edit_message_text(
            "<b>User Incident Report:</b>\n\nPlease enter the User ID/Username and description of the violation below:",
            call.message.chat.id,
            call.message.message_id
        )
        return

    if data == "u_status_menu":
        active_warns = []
        for k, v in db.get("warnings", {}).items():
            if k.startswith(f"{user_id}_"):
                cid = k.split("_")[1]
                gtitle = db.get("groups", {}).get(cid, {}).get("title", f"Group {cid}")
                active_warns.append(f"• {gtitle}: <code>{v}/3 Warns</code>")

        appeals_list = [f"• ID #{aid} - {adata.get('target', 'General')} ({adata['status']})" for aid, adata in db.get("appeals", {}).items() if adata.get("user_id") == user_id]

        warns_str = "\n".join(active_warns) if active_warns else "• No active warnings."
        appeals_str = "\n".join(appeals_list) if appeals_list else "• No pending appeals."

        status_card = (
            "<b>Account Standing Overview:</b>\n\n"
            f"<b>Active Warnings:</b>\n{warns_str}\n\n"
            f"<b>Submitted Appeals:</b>\n{appeals_str}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="u_main_menu"))
        bot.edit_message_text(status_card, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Group Warn Buttons (+1 / -1)
    if data.startswith("warn_opt_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            bot.answer_callback_query(call.id, "Admin authorization required.", show_alert=True)
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
        user_warn_cache[key] = count
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
        user_warn_cache[key] = count
        save_db(db)
        bot.edit_message_text(f"Updated: User [{target_uid}] warnings ({count} of 3).", call.message.chat.id, call.message.message_id)
        return

    # Group Unban / Unmute
    if data.startswith("act_unban_"):
        _, _, target_uid, target_cid = data.split("_")
        if not is_group_admin(int(target_cid), user_id):
            bot.answer_callback_query(call.id, "Admin authorization required.", show_alert=True)
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
            bot.answer_callback_query(call.id, "Admin authorization required.", show_alert=True)
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

    # Master Admin Panel Handlers
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
        a_len = len(db.get("appeals", {}))
        stats_text = (
            "<b>Bot Analytics & Performance:</b>\n\n"
            f"• Registered Users: <code>{u_len}</code>\n"
            f"• Active Groups: <code>{g_len}</code>\n"
            f"• Total Appeals Logged: <code>{a_len}</code>\n"
            f"• Filtered Blacklist Words: <code>{w_len}</code>\n"
            f"• Custom Auto-Replies: <code>{c_len}</code>\n"
            f"• Storage Engine: <code>PostgreSQL JSONB</code>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Banned Words Submenu (Add / Delete)
    if data == "adm_banned_words":
        words = db.get("banned_words", [])
        words_list = ", ".join(words) if words else "None"
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Add Word", callback_data="adm_bw_add"),
            types.InlineKeyboardButton("Delete Word", callback_data="adm_bw_del"),
            types.InlineKeyboardButton("Back to Dashboard", callback_data="adm_back")
        )
        bot.edit_message_text(f"<b>Banned Words Blacklist:</b>\n\n<code>{words_list}</code>", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_bw_add":
        admin_state[user_id] = "adm_add_banned_word"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_banned_words"))
        bot.edit_message_text("Send the word/phrase to add to blacklist:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_bw_del":
        words = db.get("banned_words", [])
        if not words:
            bot.answer_callback_query(call.id, "No words to delete.", show_alert=True)
            return
        markup = types.InlineKeyboardMarkup(row_width=2)
        for idx, w in enumerate(words):
            markup.add(types.InlineKeyboardButton(f"❌ {w}", callback_data=f"del_bw_{idx}"))
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_banned_words"))
        bot.edit_message_text("Select a word below to remove from blacklist:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data.startswith("del_bw_"):
        idx = int(data.replace("del_bw_", ""))
        words = db.get("banned_words", [])
        if 0 <= idx < len(words):
            removed = words.pop(idx)
            db["banned_words"] = words
            save_db(db)
            bot.answer_callback_query(call.id, f"Removed '{removed}' from blacklist.")
        words = db.get("banned_words", [])
        markup = types.InlineKeyboardMarkup(row_width=2)
        for i, w in enumerate(words):
            markup.add(types.InlineKeyboardButton(f"❌ {w}", callback_data=f"del_bw_{i}"))
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_banned_words"))
        bot.edit_message_text("Select a word below to remove from blacklist:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Manage Media Submenu
    if data == "adm_media_menu":
        m = db.get("media", {})
        s_m = "Set" if m.get("start") else "None"
        b_m = "Set" if m.get("ban") else "None"
        mu_m = "Set" if m.get("mute") else "None"
        w_m = "Set" if m.get("warn") else "None"

        media_text = (
            "<b>Manage Command Media (Photo / Video / GIF):</b>\n\n"
            f"• Start Media: <code>{s_m}</code>\n"
            f"• Ban Media: <code>{b_m}</code>\n"
            f"• Mute Media: <code>{mu_m}</code>\n"
            f"• Warn Media: <code>{w_m}</code>"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Set Start Media", callback_data="mset_start"),
            types.InlineKeyboardButton("Set Ban Media", callback_data="mset_ban"),
            types.InlineKeyboardButton("Set Mute Media", callback_data="mset_mute"),
            types.InlineKeyboardButton("Set Warn Media", callback_data="mset_warn"),
            types.InlineKeyboardButton("Reset All Media", callback_data="mset_reset_all"),
            types.InlineKeyboardButton("Back to Dashboard", callback_data="adm_back")
        )
        bot.edit_message_text(media_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data.startswith("mset_") and data != "mset_reset_all":
        target_m = data.replace("mset_", "")
        admin_state[user_id] = f"media_set_{target_m}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_media_menu"))
        bot.edit_message_text(f"Please send the Photo, Video, or GIF you want to set for <b>{target_m.upper()}</b>:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "mset_reset_all":
        db["media"] = {"start": None, "ban": None, "mute": None, "warn": None}
        save_db(db)
        bot.answer_callback_query(call.id, "All command media has been reset.")
        media_text = (
            "<b>Manage Command Media (Photo / Video / GIF):</b>\n\n"
            "• Start Media: <code>None</code>\n"
            "• Ban Media: <code>None</code>\n"
            "• Mute Media: <code>None</code>\n"
            "• Warn Media: <code>None</code>"
        )
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Set Start Media", callback_data="mset_start"),
            types.InlineKeyboardButton("Set Ban Media", callback_data="mset_ban"),
            types.InlineKeyboardButton("Set Mute Media", callback_data="mset_mute"),
            types.InlineKeyboardButton("Set Warn Media", callback_data="mset_warn"),
            types.InlineKeyboardButton("Reset All Media", callback_data="mset_reset_all"),
            types.InlineKeyboardButton("Back to Dashboard", callback_data="adm_back")
        )
        bot.edit_message_text(media_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Broadcast Targets
    if data == "adm_mailing_select":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("Both (Users + Groups)", callback_data="mail_both"),
            types.InlineKeyboardButton("Users Only", callback_data="mail_users"),
            types.InlineKeyboardButton("Groups Only", callback_data="mail_groups"),
            types.InlineKeyboardButton("Back to Dashboard", callback_data="adm_back")
        )
        bot.edit_message_text("Select broadcast target audience:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data.startswith("mail_"):
        target_mode = data.replace("mail_", "")
        admin_state[user_id] = f"broadcast_{target_mode}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_back"))
        bot.edit_message_text(f"Broadcast Mode ({target_mode.upper()}):\n\nSend or forward the message you want to broadcast:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_custom_replies":
        admin_state[user_id] = "cr_step1_trigger"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_back"))
        bot.edit_message_text("Custom Reply Setup:\n\nStep 1: Send the trigger word or phrase:", call.message.chat.id, call.message.message_id, reply_markup=markup)
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
        bot.edit_message_text("<b>Authorized Administrators:</b>\n\n" + "\n".join(lines), call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_back":
        admin_state.pop(user_id, None)
        bot.edit_message_text("<b>Administrator Control Panel</b>\nChoose a category below to manage settings:", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        return

# ----------------- ROBUST POLLING LOOP (AUTO CONFLICT RESOLVER) -----------------
def start_safe_polling():
    while True:
        try:
            print("[BOT] Attempting Telegram connection...", flush=True)
            try:
                bot.remove_webhook()
            except Exception:
                pass
            setup_bot_commands()
            time.sleep(1)
            print("[BOT] Infinity Polling active and listening.", flush=True)
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as err:
            err_str = str(err).lower()
            if "409" in err_str or "conflict" in err_str:
                wait_time = random.randint(5, 10)
                print(f"[BOT CONFLICT DETECTED] Overlapping deploy instance detected. Waiting {wait_time}s for cleanup...", flush=True)
                time.sleep(wait_time)
            else:
                print(f"[BOT POLLING ERROR] {err}. Reconnecting in 5s...", flush=True)
                time.sleep(5)

if __name__ == "__main__":
    start_safe_polling()
