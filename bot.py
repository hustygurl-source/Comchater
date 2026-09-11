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

# Centralized Channels & Groups
APPEAL_REPORT_CHAT = "@appealreport"
SCAM_HUB_CHAT = "@scamreporthub"
SELL_HUB_LINK = "https://t.me/+-wIzWjIOv9swNTk1"

if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN missing!", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", disable_web_page_preview=True)

# ----------------- 24/7 WEB SERVER FOR RENDER -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Moderation & Support Bot is Live 24/7")

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
        "restrictions": {},
        "banned_words": ["gali", "madarchod", "bhenchod", "bhosdike", "chutiya", "randi"],
        "custom_replies": {},
        "appeals": {},
        "reports": {},
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
                    if "restrictions" not in data:
                        data["restrictions"] = {}
                    if "reports" not in data:
                        data["reports"] = {}
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

# In-Memory Trackers
admin_state = {}
user_message_history = {}
user_warn_cache = {}
last_user_message = {}
report_wizard_state = {}
IST = timezone(timedelta(hours=5, minutes=30))

# ----------------- KUNDLI PREDICTIONS LIST -----------------
KUNDLI_PREDICTIONS = [
    "Aaj group mein crush se reply aane ke poore chance hain.",
    "Shani bhaari hai, aaj admin se warn lagne ke 99% aasaar hain.",
    "Kismat me single rehna likha hai, group me flirt karke time waste mat karo.",
    "Aaj tumhara koi msg delete hone wala hai spamming ki wajah se.",
    "Raahu ki dasha chal rahi hai, deal karte waqt scammer se 2 gaj doori rakhein.",
    "Aapki kundli kehti hai ki aaj koi aapke msg ko seen karke ignore karega.",
    "Aapko jald hi group me samman aur izzat milne ke yog ban rahe hain.",
    "Aaj aapka Wi-Fi connection dhokha dega jab sabse zaroori reply dena hoga.",
    "Graho ki sthiti bata rahi hai ki aaj aapka roast hone wala hai.",
    "Aapka din shubh hai, appeal karoge to turant accept ho jayegi.",
    "Group me faltu gyan dene se bachein, warna mute hone ke yog prabal hain.",
    "Mangal strong hai! Aaj kisi ladai me beech me mat padna.",
    "Aaj aapki DP dekh kar 2 log secret admirer banne wale hain.",
    "Aaj lottery lag sakti hai, bas kisi fake giveaway me participate mat karna.",
    "Aapki kundli me likha hai: 'Padhai-likhai karo, Telegram par timepass band karo'.",
    "Grah bata rahe hain ki aaj aapka tag notification sabse zyada bajega.",
    "Aaj aap jo bhi meme bhejoge, uspar 0 reaction aayenge.",
    "Ketu ke prabhav se aaj aapka keyboard galat spelling type karwayega.",
    "Aapki life me shanti tabhi aayegi jab phone side me rakh kar so jaoge.",
    "Aaj crush online aayegi lekin kisi aur ke funny sticker par react karegi.",
    "Aapke sitaare buland hain, aaj crypto aur trading me fayda hoga."
]

# ----------------- HARD RESET & SETUP COMMAND SCOPES -----------------
def setup_bot_commands():
    try:
        scopes_to_clear = [
            types.BotCommandScopeDefault(),
            types.BotCommandScopeAllPrivateChats(),
            types.BotCommandScopeAllGroupChats(),
            types.BotCommandScopeAllChatAdministrators()
        ]
        for sc in scopes_to_clear:
            try:
                bot.delete_my_commands(scope=sc)
            except Exception:
                pass
        
        time.sleep(1)

        private_cmds = [
            types.BotCommand("start", "Open Support Portal"),
            types.BotCommand("claim", "Verify secret admin key"),
            types.BotCommand("admin", "Open Administrator Panel")
        ]
        bot.set_my_commands(private_cmds, scope=types.BotCommandScopeAllPrivateChats())

        group_cmds = [
            types.BotCommand("warn", "Warn a user [reply/id/username]"),
            types.BotCommand("unwarn", "Remove user warning"),
            types.BotCommand("mute", "Mute a user [reply/id/username]"),
            types.BotCommand("unmute", "Unmute a user [reply/id/username]"),
            types.BotCommand("ban", "Ban a user [reply/id/username]"),
            types.BotCommand("unban", "Unban a user [reply/id/username]"),
            types.BotCommand("info", "Show user information"),
            types.BotCommand("matchmaker", "Calculate love match [reply/mention]"),
            types.BotCommand("kundli", "Get daily fun horoscope & roast")
        ]
        bot.set_my_commands(group_cmds, scope=types.BotCommandScopeAllGroupChats())
        print("[BOT] Old commands killed & new scopes registered successfully.", flush=True)
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

def get_user_mention(user_id, name, username=None):
    if username:
        return f"@{username.replace('@', '')}"
    return f"<a href='tg://user?id={user_id}'>{name}</a>"

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
                f"• User: {get_user_mention(user.id, user.first_name, user.username)}\n"
                f"• User ID: <code>{user.id}</code>\n"
                f"• Username: {u_tag}\n"
                f"• Date: <code>{get_full_timestamp()}</code>"
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

def resolve_target_id(target_str):
    target_str = str(target_str).replace("@", "").strip()
    if target_str.isdigit():
        return int(target_str)
    for u in db.get("users", {}).values():
        if u.get("username", "").lower().replace("@", "") == target_str.lower():
            return int(u["id"])
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
        types.InlineKeyboardButton("Sell Hub", callback_data="appeal_target_Sell Hub"),
        types.InlineKeyboardButton("Comchater", callback_data="appeal_target_Comchater"),
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
        f"<b>Welcome, {get_user_mention(user.id, user.first_name, user.username)}</b>\n\n"
        "This is the official Group Moderation Support & Appeal Desk.\n"
        "Please select an option below:\n\n"
        "<i>Powered by @jyoex</i>"
    )
    send_with_optional_media(message.chat.id, "start", welcome_text, get_user_main_markup())

@bot.message_handler(commands=['claim'], chat_types=['private'])
def handle_claim_command(message):
    user_id = message.from_user.id
    if is_admin_or_owner(user_id):
        bot.reply_to(message, "You are already authorized as an Admin. Use <code>/admin</code> to open panel.")
        return

    admin_state[user_id] = "waiting_claim_password"
    bot.reply_to(message, f"{get_user_mention(user_id, message.from_user.first_name)}, please enter the secret admin access key:")

@bot.message_handler(commands=['admin'], chat_types=['private'])
def handle_admin_command(message):
    if not is_admin_or_owner(message.from_user.id):
        bot.reply_to(message, "Access Denied. Send <code>/claim</code> to authenticate first.")
        return
    bot.reply_to(message, "<b>Administrator Control Panel</b>\nSelect an option below to manage settings:", reply_markup=get_admin_panel_markup())

# ----------------- GROUP FUN COMMANDS -----------------
@bot.message_handler(commands=['matchmaker'], chat_types=['group', 'supergroup'])
def cmd_matchmaker(message):
    user1 = message.from_user
    user2 = None

    args = message.text.split()
    if message.reply_to_message:
        user2 = message.reply_to_message.from_user
        if len(args) > 1:
            target_str = args[1].replace("@", "")
            for u in db.get("users", {}).values():
                if u.get("username", "").lower().replace("@", "") == target_str.lower():
                    user1 = types.User(u["id"], False, u["name"], username=target_str)
                    break
    elif len(args) > 1:
        target_str = args[1].replace("@", "")
        for u in db.get("users", {}).values():
            if u.get("username", "").lower().replace("@", "") == target_str.lower():
                user2 = types.User(u["id"], False, u["name"], username=target_str)
                break

    if not user2 or user1.id == user2.id:
        bot.reply_to(message, "Usage: Reply to a message with <code>/matchmaker</code> or mention a username: <code>/matchmaker @username</code>")
        return

    combined_id = int(user1.id) + int(user2.id)
    random.seed(combined_id + int(time.strftime("%d%m%Y")))
    percentage = random.randint(15, 100)

    if percentage > 80:
        remark = "Match score bohot solid hai. Perfect pair."
    elif percentage > 50:
        remark = "Achhi chemistry hai, baat aage badh sakti hai."
    elif percentage > 30:
        remark = "Normal dosti tak hi theek hai."
    else:
        remark = "Compatibility bohot kam hai, doori banaye rakhein."

    u1_tag = get_user_mention(user1.id, user1.first_name, user1.username)
    u2_tag = get_user_mention(user2.id, user2.first_name, user2.username)

    match_text = (
        "<b>Matchmaker Report:</b>\n\n"
        f"• User 1: {u1_tag}\n"
        f"• User 2: {u2_tag}\n"
        f"• Compatibility: <b>{percentage}%</b>\n\n"
        f"<b>Verdict:</b> {remark}"
    )
    bot.reply_to(message, match_text)

@bot.message_handler(commands=['kundli'], chat_types=['group', 'supergroup'])
def cmd_kundli(message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    t_tag = get_user_mention(target.id, target.first_name, target.username)

    prediction = random.choice(KUNDLI_PREDICTIONS)
    score = random.randint(20, 100)

    kundli_card = (
        f"<b>Dainik Kundli:</b>\n"
        f"User: {t_tag}\n\n"
        f"<b>Prediction:</b>\n"
        f"\"{prediction}\"\n\n"
        f"• Score: <b>{score}/100</b>"
    )
    bot.reply_to(message, kundli_card)

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

    uname = get_user_mention(target.id, target.first_name, target.username)

    if curr_warns < 3:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{target.id}_{chat.id}"))
        warn_msg = f"{uname} [{target.id}] warned ({curr_warns} of 3)."
        send_with_optional_media(chat.id, "warn", warn_msg, markup)
    else:
        db["warnings"].pop(key, None)
        user_warn_cache.pop(key, None)

        db.setdefault("restrictions", {})[str(target.id)] = {
            "type": "Muted",
            "chat_id": chat.id,
            "chat_title": chat.title,
            "reason": "3 Warnings Reached (Admin/Spam)",
            "last_msg": last_user_message.get(target.id, "N/A"),
            "date": get_full_timestamp()
        }
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

    uname = get_user_mention(target.id, target.first_name, target.username)
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

    uname = get_user_mention(target.id, target.first_name, target.username)
    try:
        bot.restrict_chat_member(chat.id, target.id, can_send_messages=False)

        db.setdefault("restrictions", {})[str(target.id)] = {
            "type": "Muted",
            "chat_id": chat.id,
            "chat_title": chat.title,
            "reason": "Direct Admin Action",
            "last_msg": last_user_message.get(target.id, "Direct Mute"),
            "date": get_full_timestamp()
        }
        save_db(db)

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

    uname = get_user_mention(target.id, target.first_name, target.username)
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

    uname = get_user_mention(target.id, target.first_name, target.username)
    try:
        bot.ban_chat_member(chat.id, target.id)

        db.setdefault("restrictions", {})[str(target.id)] = {
            "type": "Banned",
            "chat_id": chat.id,
            "chat_title": chat.title,
            "reason": "Direct Admin Action",
            "last_msg": last_user_message.get(target.id, "Direct Ban"),
            "date": get_full_timestamp()
        }
        save_db(db)

        bot_user = bot.get_me().username
        ban_dm_text = (
            f"Hello {uname},\n\nYou have been <b>banned</b> from <b>{chat.title}</b>.\n"
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

    uname = get_user_mention(target.id, target.first_name, target.username)
    try:
        bot.unban_chat_member(chat.id, target.id, only_if_banned=True)
        bot.send_message(chat.id, f"{uname} [{target.id}] has been unbanned.")
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['info'], chat_types=['group', 'supergroup'])
def cmd_info(message):
    target = get_target_user(message) or message.from_user
    chat_id = message.chat.id
    key = f"{target.id}_{chat_id}"
    warn_count = db.get("warnings", {}).get(key, 0)
    u_info = db.get("users", {}).get(str(target.id), {})
    joined = u_info.get("joined_at", "N/A")
    t_tag = get_user_mention(target.id, target.first_name, target.username)

    info_text = (
        "<b>User Record:</b>\n\n"
        f"• User: {t_tag}\n"
        f"• User ID: <code>{target.id}</code>\n"
        f"• Username: @{target.username if target.username else 'None'}\n"
        f"• Warnings in this chat: <code>{warn_count}/3</code>\n"
        f"• First Registered: <code>{joined}</code>"
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

    last_user_message[user.id] = text[:200] if text else "[Media/Sticker]"

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

    # 4. Anti-Flood: 4th message deleted instantly
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
        uname = get_user_mention(user.id, user.first_name, user.username)

        if curr_warns < 3:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"warn_opt_{user.id}_{chat.id}"))
            warn_msg = f"{uname} [{user.id}] warned ({curr_warns} of 3)."
            send_with_optional_media(chat.id, "warn", warn_msg, markup)
        else:
            db["warnings"].pop(key, None)
            user_warn_cache.pop(key, None)

            db.setdefault("restrictions", {})[str(user.id)] = {
                "type": "Muted",
                "chat_id": chat.id,
                "chat_title": chat.title,
                "reason": "Excessive Flooding (4th msg in 10s)",
                "last_msg": text[:150] if text else "[Fast Spam]",
                "date": get_full_timestamp()
            }
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

# ----------------- PRIVATE CONVERSATION & WIZARDS -----------------
@bot.message_handler(chat_types=['private'], content_types=['text', 'photo', 'video', 'document', 'audio', 'voice', 'sticker', 'animation'])
def handle_private_dialogue(message):
    user_id = message.from_user.id
    state = admin_state.get(user_id)
    text = message.text or ""
    u_tag = get_user_mention(user_id, message.from_user.first_name, message.from_user.username)

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
                f"<b>Authentication Successful:</b>\n{u_tag}, you are authorized as Master Admin. Use <code>/admin</code> to open dashboard.",
                reply_markup=get_admin_panel_markup()
            )
        else:
            bot.reply_to(message, "Incorrect authorization key.")
        return

    # Appeal Explanation Processing
    if state.startswith("submitting_appeal_"):
        target_group = state.replace("submitting_appeal_", "")

        # 1. Profanity check
        for bw in db.get("banned_words", []):
            if bw in text.lower():
                bot.reply_to(
                    message,
                    f"{u_tag}, <b>Appeal Rejected:</b>\nAbusive language is strictly prohibited. Please rewrite your explanation politely:"
                )
                return

        # 2. Length check
        words_count = len(text.split())
        char_count = len(text.strip())

        if char_count < 50:
            bot.reply_to(
                message,
                f"{u_tag}, <b>Appeal Too Short:</b>\nYour statement has {char_count} characters. Please provide between 50 characters and 150 words:"
            )
            return

        if words_count > 150:
            bot.reply_to(
                message,
                f"{u_tag}, <b>Appeal Exceeds Limit:</b>\nYour statement has {words_count} words (Maximum: 150 words). Please make it concise:"
            )
            return

        admin_state.pop(user_id, None)
        appeal_id = str(int(time.time()))

        r_info = db.get("restrictions", {}).get(str(user_id), {
            "type": "Muted/Banned",
            "chat_id": 0,
            "chat_title": target_group,
            "reason": "Group Policy Infraction",
            "last_msg": "N/A"
        })

        db.setdefault("appeals", {})[appeal_id] = {
            "user_id": user_id,
            "target": target_group,
            "chat_id": r_info.get("chat_id", 0),
            "chat_title": r_info.get("chat_title", target_group),
            "res_type": r_info.get("type", "Restriction"),
            "name": message.from_user.first_name,
            "username": message.from_user.username,
            "text": text,
            "status": "Pending",
            "time": get_full_timestamp()
        }
        save_db(db)

        # Forward Card to Central Group (@appealreport)
        appeal_card = (
            f"<b>NEW APPEAL CASE [ID: #{appeal_id}]</b>\n\n"
            f"• <b>User:</b> {u_tag} [<code>{user_id}</code>]\n"
            f"• <b>Target Community:</b> {target_group}\n"
            f"• <b>Status in Group:</b> {r_info.get('type', 'Muted')}\n"
            f"• <b>Trigger Reason:</b> <code>{r_info.get('reason', 'Violation')}</code>\n"
            f"• <b>Last Message:</b> <i>\"{r_info.get('last_msg', 'N/A')}\"</i>\n"
            f"• <b>Time:</b> <code>{get_full_timestamp()}</code>\n\n"
            f"<b>User Explanation:</b>\n{text}"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        if r_info.get("type") == "Banned":
            markup.add(
                types.InlineKeyboardButton("Reject Appeal", callback_data=f"app_rej_{appeal_id}"),
                types.InlineKeyboardButton("Unban & Approve", callback_data=f"app_appr_ban_{appeal_id}")
            )
        else:
            markup.add(
                types.InlineKeyboardButton("Reject Appeal", callback_data=f"app_rej_{appeal_id}"),
                types.InlineKeyboardButton("Unmute & Approve", callback_data=f"app_appr_mute_{appeal_id}")
            )

        try:
            bot.send_message(APPEAL_REPORT_CHAT, appeal_card, reply_markup=markup)
        except Exception as e:
            print(f"[APPEAL FORWARD ERROR] {e}", flush=True)

        bot.reply_to(
            message,
            f"{u_tag}, your appeal has been successfully submitted. Our moderation team will review your case shortly."
        )
        return

    # Scam Report 4-Step Wizard
    if state == "rep_step1_target":
        target_val = text.strip()
        if not (target_val.startswith("@") or target_val.isdigit() or len(target_val) >= 4):
            bot.reply_to(message, f"{u_tag}, please enter a valid Telegram @username or numeric User ID:")
            return

        report_wizard_state[user_id] = {"target": target_val}
        admin_state[user_id] = "rep_step2_amount"
        bot.reply_to(
            message,
            f"{u_tag}, <b>Step 2: Deal Amount:</b>\nEnter the scammed amount/value (e.g. <code>$50</code>, <code>₹2500</code>) or send <code>/skip</code> if not applicable:"
        )
        return

    if state == "rep_step2_amount":
        amount_val = "Not specified" if text.lower() == "/skip" else text.strip()
        report_wizard_state.setdefault(user_id, {})["amount"] = amount_val
        admin_state[user_id] = "rep_step3_summary"
        bot.reply_to(
            message,
            f"{u_tag}, <b>Step 3: Incident Summary:</b>\nPlease write a concise explanation of what happened:"
        )
        return

    if state == "rep_step3_summary":
        report_wizard_state.setdefault(user_id, {})["summary"] = text.strip()
        admin_state[user_id] = "rep_step4_proof"
        bot.reply_to(
            message,
            f"{u_tag}, <b>Step 4: Proof Channel/Group Link:</b>\nPlease create a private channel/group containing all screenshots/proof and paste the invite link here:"
        )
        return

    if state == "rep_step4_proof":
        proof_link = text.strip()
        rep_data = report_wizard_state.pop(user_id, {})
        admin_state.pop(user_id, None)

        report_id = str(int(time.time()))
        db.setdefault("reports", {})[report_id] = {
            "report_id": report_id,
            "reporter_id": user_id,
            "reporter_name": message.from_user.first_name,
            "reporter_username": message.from_user.username,
            "target": rep_data.get("target", "Unknown"),
            "amount": rep_data.get("amount", "N/A"),
            "summary": rep_data.get("summary", "N/A"),
            "proof": proof_link,
            "time": get_full_timestamp(),
            "status": "Pending"
        }
        save_db(db)

        # Forward Report Card to Central Group (@appealreport)
        report_card = (
            f"<b>NEW SCAM REPORT [CASE #{report_id}]</b>\n\n"
            f"• <b>Reported Scammer:</b> <code>{rep_data.get('target')}</code>\n"
            f"• <b>Submitted By:</b> {u_tag} [<code>{user_id}</code>]\n"
            f"• <b>Deal Value:</b> <code>{rep_data.get('amount')}</code>\n"
            f"• <b>Proof Link:</b> {proof_link}\n"
            f"• <b>Date:</b> <code>{get_full_timestamp()}</code>\n\n"
            f"<b>Summary:</b>\n{rep_data.get('summary')}"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Post to Scam Hub", callback_data=f"rep_posthub_{report_id}"),
            types.InlineKeyboardButton("Dismiss", callback_data=f"rep_dismiss_{report_id}"),
            types.InlineKeyboardButton("Ban User", callback_data=f"rep_ban_{report_id}"),
            types.InlineKeyboardButton("Mute User", callback_data=f"rep_mute_{report_id}")
        )

        try:
            bot.send_message(APPEAL_REPORT_CHAT, report_card, reply_markup=markup)
        except Exception as e:
            print(f"[REPORT FORWARD ERROR] {e}", flush=True)

        bot.reply_to(
            message,
            f"{u_tag}, your scam report has been submitted to the moderation desk for verification."
        )
        return

    # Add Banned Word
    if state == "adm_add_banned_word":
        admin_state.pop(user_id, None)
        new_w = text.lower().strip()
        if new_w and new_w not in db.get("banned_words", []):
            db.setdefault("banned_words", []).append(new_w)
            save_db(db)
            bot.reply_to(message, f"Word '<code>{new_w}</code>' added to blacklist.", reply_markup=get_admin_panel_markup())
        else:
            bot.reply_to(message, "Word already in list or invalid.", reply_markup=get_admin_panel_markup())
        return

    # Media Setting
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
            bot.reply_to(message, "No valid photo, video or GIF detected.", reply_markup=get_admin_panel_markup())
        return

    # Custom Reply Flow
    if state == "cr_step1_trigger":
        admin_state[user_id] = f"cr_step2_text_{text.lower().strip()}"
        bot.reply_to(message, f"Trigger set: <code>{text.lower().strip()}</code>\n\nStep 2: Send the reply text:")
        return

    if state.startswith("cr_step2_text_"):
        trigger = state.replace("cr_step2_text_", "")
        admin_state[user_id] = f"cr_step3_btn_{trigger}__SPLIT__{text}"
        bot.reply_to(message, "Step 3: To attach a button: <code>Button Title | https://link.com</code>\nOr type <code>skip</code> for text only.")
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
        bot.reply_to(message, "Custom auto-reply saved.", reply_markup=get_admin_panel_markup())
        return

    # Broadcast Flow
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
    u_tag = get_user_mention(user_id, call.from_user.first_name, call.from_user.username)

    # User Navigation
    if data == "u_main_menu":
        admin_state.pop(user_id, None)
        welcome_text = (
            f"<b>Welcome, {u_tag}</b>\n\n"
            "This is the official Group Moderation Support & Appeal Desk.\n"
            "Please select an option below:\n\n"
            "<i>Powered by @jyoex</i>"
        )
        bot.edit_message_text(welcome_text, call.message.chat.id, call.message.message_id, reply_markup=get_user_main_markup())
        return

    if data == "u_appeal_menu":
        bot.edit_message_text(
            f"{u_tag}, please choose the community where you are restricted:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_appeal_target_markup()
        )
        return

    if data.startswith("appeal_target_"):
        target_group = data.replace("appeal_target_", "")
        admin_state[user_id] = f"submitting_appeal_{target_group}"
        prompt = (
            f"<b>Appeal Submission for {target_group}:</b>\n\n"
            f"{u_tag}, please describe why you were restricted in the group and why the restriction should be lifted.\n\n"
            "<b>Guidelines:</b>\n"
            "• Length: Minimum 50 characters, Maximum 150 words.\n"
            "• Abusive language will result in automatic rejection."
        )
        bot.edit_message_text(prompt, call.message.chat.id, call.message.message_id)
        return

    if data == "u_report_menu":
        admin_state[user_id] = "rep_step1_target"
        bot.edit_message_text(
            f"{u_tag}, <b>Step 1: Scammer Identifier:</b>\nPlease enter the User ID or @username of the person you are reporting:",
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

        appeals_list = [f"• #{aid} - {adata.get('target', 'General')} ({adata['status']})" for aid, adata in db.get("appeals", {}).items() if adata.get("user_id") == user_id]

        warns_str = "\n".join(active_warns) if active_warns else "• No active warnings."
        appeals_str = "\n".join(appeals_list) if appeals_list else "• No pending appeals."

        status_card = (
            f"<b>Account Standing Overview for {u_tag}:</b>\n\n"
            f"<b>Active Warnings:</b>\n{warns_str}\n\n"
            f"<b>Appeal Submissions:</b>\n{appeals_str}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="u_main_menu"))
        bot.edit_message_text(status_card, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Appeal Decisions in Central Group (@appealreport)
    if data.startswith("app_rej_"):
        appeal_id = data.replace("app_rej_", "")
        appeal = db.get("appeals", {}).get(appeal_id)
        if appeal:
            appeal["status"] = "Rejected"
            save_db(db)
            target_uid = appeal["user_id"]
            t_user_tag = get_user_mention(target_uid, appeal.get("name", "User"), appeal.get("username"))

            try:
                bot.send_message(target_uid, f"Hello {t_user_tag},\n\nYour appeal for <b>{appeal.get('target')}</b> has been reviewed and <b>rejected</b> by moderators.")
            except Exception:
                pass

            bot.edit_message_text(
                call.message.text + f"\n\n<b>Status:</b> Rejected by {call.from_user.first_name}",
                call.message.chat.id,
                call.message.message_id
            )
        return

    if data.startswith("app_appr_"):
        parts = data.split("_")
        action_mode = parts[2]
        appeal_id = parts[3]
        appeal = db.get("appeals", {}).get(appeal_id)

        if appeal:
            appeal["status"] = "Approved"
            save_db(db)
            target_uid = appeal["user_id"]
            cid = appeal.get("chat_id")
            t_user_tag = get_user_mention(target_uid, appeal.get("name", "User"), appeal.get("username"))

            if cid:
                try:
                    if action_mode == "ban":
                        bot.unban_chat_member(int(cid), int(target_uid), only_if_banned=True)
                    else:
                        bot.restrict_chat_member(
                            int(cid), int(target_uid),
                            can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True
                        )
                except Exception:
                    pass

            join_link = SELL_HUB_LINK if "Sell" in appeal.get("target", "") else "https://t.me/comchater"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Rejoin Group", url=join_link))

            try:
                bot.send_message(
                    target_uid,
                    f"Hello {t_user_tag},\n\nGood news! Your appeal for <b>{appeal.get('target')}</b> has been <b>approved</b>! Your restriction has been lifted.",
                    reply_markup=markup
                )
            except Exception:
                pass

            bot.edit_message_text(
                call.message.text + f"\n\n<b>Status:</b> Approved & Restored by {call.from_user.first_name}",
                call.message.chat.id,
                call.message.message_id
            )
        return

    # Scam Report Actions (@appealreport)
    if data.startswith("rep_posthub_"):
        report_id = data.replace("rep_posthub_", "")
        rep = db.get("reports", {}).get(report_id)
        if rep:
            hub_post = (
                "<b>OFFICIAL SCAM ALERT</b>\n\n"
                f"• <b>Scammer Identifier:</b> <code>{rep['target']}</code>\n"
                f"• <b>Scammed Amount:</b> <code>{rep['amount']}</code>\n"
                f"• <b>Evidence Link:</b> {rep['proof']}\n"
                f"• <b>Date:</b> <code>{get_full_timestamp()}</code>\n\n"
                f"<b>Summary:</b>\n{rep['summary']}\n\n"
                "<i>Beware of dealing with this entity. Always use trusted escrows.</i>"
            )
            try:
                bot.send_message(SCAM_HUB_CHAT, hub_post)
                bot.answer_callback_query(call.id, "Alert published to Scam Hub.")
                bot.edit_message_text(
                    call.message.text + f"\n\n<b>Action:</b> Published to Scam Hub by {call.from_user.first_name}",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception as e:
                bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)
        return

    if data.startswith("rep_ban_"):
        report_id = data.replace("rep_ban_", "")
        rep = db.get("reports", {}).get(report_id)
        if rep:
            target_raw = rep.get("target", "")
            target_uid = resolve_target_id(target_raw)
            if target_uid:
                for gid in db.get("groups", {}).keys():
                    try:
                        bot.ban_chat_member(int(gid), target_uid)
                    except Exception:
                        pass
                bot.answer_callback_query(call.id, f"User {target_raw} banned from groups.")
                bot.edit_message_text(
                    call.message.text + f"\n\n<b>Action:</b> Scammer Banned across groups by {call.from_user.first_name}",
                    call.message.chat.id,
                    call.message.message_id
                )
            else:
                bot.answer_callback_query(call.id, "Numeric User ID not found to execute group ban.", show_alert=True)
        return

    if data.startswith("rep_mute_"):
        report_id = data.replace("rep_mute_", "")
        rep = db.get("reports", {}).get(report_id)
        if rep:
            target_raw = rep.get("target", "")
            target_uid = resolve_target_id(target_raw)
            if target_uid:
                for gid in db.get("groups", {}).keys():
                    try:
                        bot.restrict_chat_member(int(gid), target_uid, can_send_messages=False)
                    except Exception:
                        pass
                bot.answer_callback_query(call.id, f"User {target_raw} muted in groups.")
                bot.edit_message_text(
                    call.message.text + f"\n\n<b>Action:</b> Scammer Muted across groups by {call.from_user.first_name}",
                    call.message.chat.id,
                    call.message.message_id
                )
            else:
                bot.answer_callback_query(call.id, "Numeric User ID not found to execute group mute.", show_alert=True)
        return

    if data.startswith("rep_dismiss_"):
        bot.edit_message_text(
            call.message.text + f"\n\n<b>Action:</b> Dismissed by {call.from_user.first_name}",
            call.message.chat.id,
            call.message.message_id
        )
        return

    # Group Warn In-line Buttons
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

    # Group Unban / Unmute Handlers
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

    # Master Admin Panel
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
        r_len = len(db.get("reports", {}))
        stats_text = (
            "<b>Bot Analytics & Performance:</b>\n\n"
            f"• Registered Users: <code>{u_len}</code>\n"
            f"• Active Groups: <code>{g_len}</code>\n"
            f"• Total Appeals Handled: <code>{a_len}</code>\n"
            f"• Scam Reports Logged: <code>{r_len}</code>\n"
            f"• Filtered Blacklist Words: <code>{w_len}</code>\n"
            f"• Custom Auto-Replies: <code>{c_len}</code>\n"
            f"• Storage: <code>Neon PostgreSQL JSONB</code>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_back"))
        bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Banned Words Submenu
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
            markup.add(types.InlineKeyboardButton(f"Remove: {w}", callback_data=f"del_bw_{idx}"))
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
            markup.add(types.InlineKeyboardButton(f"Remove: {w}", callback_data=f"del_bw_{i}"))
        markup.add(types.InlineKeyboardButton("Back", callback_data="adm_banned_words"))
        bot.edit_message_text("Select a word below to remove from blacklist:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    # Media Management Menu
    if data == "adm_media_menu":
        m = db.get("media", {})
        s_m = "Set" if m.get("start") else "None"
        b_m = "Set" if m.get("ban") else "None"
        mu_m = "Set" if m.get("mute") else "None"
        w_m = "Set" if m.get("warn") else "None"

        media_text = (
            "<b>Manage Command Media:</b>\n\n"
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
            "<b>Manage Command Media:</b>\n\n"
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
        bot.edit_message_text(f"Broadcast Mode ({target_mode.upper()}):\n\nSend or forward the message to broadcast:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return

    if data == "adm_custom_replies":
        admin_state[user_id] = "cr_step1_trigger"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="adm_back"))
        bot.edit_message_text("Custom Reply Setup:\n\nStep 1: Send the trigger keyword:", call.message.chat.id, call.message.message_id, reply_markup=markup)
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
        bot.edit_message_text("<b>Administrator Control Panel</b>\nSelect an option below to manage settings:", call.message.chat.id, call.message.message_id, reply_markup=get_admin_panel_markup())
        return

# ----------------- ENTRYPOINT & SAFE POLLING LOOP -----------------
def start_safe_polling():
    while True:
        try:
            me = bot.get_me()
            print(f"[BOT] Active and polling as @{me.username} (ID: {me.id})", flush=True)
            bot.remove_webhook()
            setup_bot_commands()
            time.sleep(2)
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"[BOT RECOVERY] Loop error: {e}. Retrying in 5 seconds...", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    start_safe_polling()
