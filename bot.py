import os
import re
import time
import threading
from collections import defaultdict
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import database as db

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# State variables
user_message_history = defaultdict(list)
user_states = {}

# Flask app for Render Web Service + Uptime Monitor
app_flask = Flask(__name__)

@app_flask.route('/')
def home():
    return "Bot status: Active"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

# Helper: Check Admin Status
async def is_admin(chat, user_id, bot):
    try:
        member = await bot.get_chat_member(chat.id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False

# ----------------- User Message Handler & Anti-Spam ----------------- #

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type == "private":
        return

    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not user or user.is_bot:
        return

    db.add_group(chat.id, chat.title)
    is_user_admin = await is_admin(chat, user.id, context.bot)

    # 1. Custom Trigger Replies
    text_content = msg.text or msg.caption or ""
    if text_content:
        for cr in db.get_custom_replies():
            if cr['trigger'] in text_content.lower():
                keyboard = []
                if cr['btn_name'] and cr['btn_url']:
                    keyboard.append([InlineKeyboardButton(cr['btn_name'], url=cr['btn_url'])])
                markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                await msg.reply_text(cr['reply_text'], reply_markup=markup)
                break

    # Admin bypass for moderation rules
    if is_user_admin:
        return

    # 2. Anti-Link Filter
    url_pattern = r"(https?://\S+|www\.\S+|t\.me/\S+)"
    if re.search(url_pattern, text_content):
        try:
            await msg.delete()
            return
        except Exception:
            pass

    # 3. Banned Words Filter
    for word in db.get_banned_words():
        if word in text_content.lower():
            try:
                await msg.delete()
                return
            except Exception:
                pass

    # 4. Anti-Flood Logic (10s window, max 3 messages)
    now = time.time()
    user_message_history[user.id] = [t for t in user_message_history[user.id] if now - t <= 10]
    user_message_history[user.id].append(now)

    if len(user_message_history[user.id]) > 3:
        try:
            await msg.delete()
        except Exception:
            pass

        count = db.update_warns(user.id, chat.id, 1)
        uname = f"@{user.username}" if user.username else user.first_name

        if count < 3:
            keyboard = [[InlineKeyboardButton("✖ Cancel", callback_data=f"warn_opt_{user.id}_{chat.id}")]]
            text = f"{uname} [{user.id}] warned ({count} of 3)."
            await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            db.reset_warns(user.id, chat.id)
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception:
                pass
            
            bot_info = await context.bot.get_me()
            keyboard = [
                [
                    InlineKeyboardButton("📝 Appeal", url=f"https://t.me/{bot_info.username}?start=appeal_{chat.id}"),
                    InlineKeyboardButton("✅ Unban", callback_data=f"act_unban_{user.id}_{chat.id}")
                ]
            ]
            text = f"{uname} [{user.id}] banned."
            await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ----------------- Anti-Bot Add (Delete Added Bots) ----------------- #

async def handle_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not msg.new_chat_members:
        return

    is_adder_admin = await is_admin(chat, user.id, context.bot)

    for member in msg.new_chat_members:
        if member.is_bot:
            if not is_adder_admin:
                try:
                    # Remove the bot added by normal user
                    await context.bot.ban_chat_member(chat.id, member.id)
                    await msg.delete()
                except Exception:
                    pass

# ----------------- Manual Admin Commands ----------------- #

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not await is_admin(chat, user.id, context.bot):
        return

    if not msg.reply_to_message:
        await msg.reply_text("Reply to a user's message to warn them.")
        return

    target = msg.reply_to_message.from_user
    count = db.update_warns(target.id, chat.id, 1)
    uname = f"@{target.username}" if target.username else target.first_name

    if count < 3:
        keyboard = [[InlineKeyboardButton("✖ Cancel", callback_data=f"warn_opt_{target.id}_{chat.id}")]]
        text = f"{uname} [{target.id}] warned ({count} of 3)."
        await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        db.reset_warns(target.id, chat.id)
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target.id)
        bot_info = await context.bot.get_me()
        keyboard = [
            [
                InlineKeyboardButton("📝 Appeal", url=f"https://t.me/{bot_info.username}?start=appeal_{chat.id}"),
                InlineKeyboardButton("✅ Unban", callback_data=f"act_unban_{target.id}_{chat.id}")
            ]
        ]
        text = f"{uname} [{target.id}] banned."
        await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not await is_admin(chat, user.id, context.bot):
        return

    if not msg.reply_to_message:
        await msg.reply_text("Reply to a user's message to mute them.")
        return

    target = msg.reply_to_message.from_user
    uname = f"@{target.username}" if target.username else target.first_name

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        bot_info = await context.bot.get_me()
        keyboard = [
            [
                InlineKeyboardButton("📝 Appeal", url=f"https://t.me/{bot_info.username}?start=appeal_{chat.id}"),
                InlineKeyboardButton("✅ Unmute", callback_data=f"act_unmute_{target.id}_{chat.id}")
            ]
        ]
        text = f"{uname} [{target.id}] has been 🔇 muted."
        await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await msg.reply_text(f"Error: {e}")

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message

    if not await is_admin(chat, user.id, context.bot):
        return

    if not msg.reply_to_message:
        await msg.reply_text("Reply to a user's message to ban them.")
        return

    target = msg.reply_to_message.from_user
    uname = f"@{target.username}" if target.username else target.first_name

    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=target.id)
        bot_info = await context.bot.get_me()
        keyboard = [
            [
                InlineKeyboardButton("📝 Appeal", url=f"https://t.me/{bot_info.username}?start=appeal_{chat.id}"),
                InlineKeyboardButton("✅ Unban", callback_data=f"act_unban_{target.id}_{chat.id}")
            ]
        ]
        text = f"{uname} [{target.id}] banned."
        await chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await msg.reply_text(f"Error: {e}")

# ----------------- User Private Start & Admin Dashboard ----------------- #

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username)

    args = context.args
    if args and args[0].startswith("appeal_"):
        target_chat_id = args[0].replace("appeal_", "")
        user_states[user.id] = {"action": "submitting_appeal", "chat_id": target_chat_id}
        await update.message.reply_text("Ban/Mute Appeal Portal:\n\nType your appeal message below. It will be sent to admins.")
        return

    keyboard = [
        [InlineKeyboardButton("📝 Submit Appeal", callback_data="u_appeal"), InlineKeyboardButton("🚨 Report", callback_data="u_report")],
        [InlineKeyboardButton("📊 My Warnings", callback_data="u_warns"), InlineKeyboardButton("📜 Rules", callback_data="u_rules")]
    ]
    await update.message.reply_text("Welcome to Help & Moderation Bot.\nChoose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != OWNER_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📬 Mailing", callback_data="adm_mailing"), InlineKeyboardButton("📊 Statistics", callback_data="adm_stats")],
        [InlineKeyboardButton("🚫 Banned Words", callback_data="adm_banned_words"), InlineKeyboardButton("💬 Custom Replies", callback_data="adm_custom_replies")],
        [InlineKeyboardButton("✖ Close Panel", callback_data="adm_close")]
    ]
    await update.message.reply_text("Administrator Control Panel\nSelect an action from the options below:", reply_markup=InlineKeyboardMarkup(keyboard))

# ----------------- Callback Query Handling ----------------- #

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = update.effective_user
    await query.answer()

    # Warn Button adjustments (+1 / -1)
    if data.startswith("warn_opt_"):
        _, _, target_uid, target_cid = data.split("_")
        keyboard = [
            [
                InlineKeyboardButton("➕ +1", callback_data=f"warn_add_{target_uid}_{target_cid}"),
                InlineKeyboardButton("➖ -1", callback_data=f"warn_sub_{target_uid}_{target_cid}")
            ]
        ]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("warn_add_"):
        _, _, target_uid, target_cid = data.split("_")
        count = db.update_warns(int(target_uid), int(target_cid), 1)
        await query.edit_message_text(f"Updated: User [{target_uid}] warning count is now ({count} of 3).")

    elif data.startswith("warn_sub_"):
        _, _, target_uid, target_cid = data.split("_")
        count = db.update_warns(int(target_uid), int(target_cid), -1)
        await query.edit_message_text(f"Updated: User [{target_uid}] warning count is now ({count} of 3).")

    # Unban / Unmute actions
    elif data.startswith("act_unban_"):
        _, _, target_uid, target_cid = data.split("_")
        await context.bot.unban_chat_member(int(target_cid), int(target_uid), only_if_banned=True)
        await query.edit_message_text(f"User [{target_uid}] unbanned by {user.first_name}.")

    elif data.startswith("act_unmute_"):
        _, _, target_uid, target_cid = data.split("_")
        await context.bot.restrict_chat_member(
            chat_id=int(target_cid),
            user_id=int(target_uid),
            permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True)
        )
        await query.edit_message_text(f"User [{target_uid}] unmuted by {user.first_name}.")

    # Admin Dashboard Callbacks
    elif data == "adm_mailing":
        keyboard = [
            [InlineKeyboardButton("🌐 Both (Bot Users + Groups)", callback_data="bc_both")],
            [InlineKeyboardButton("👤 Bot Users Only", callback_data="bc_users")],
            [InlineKeyboardButton("👥 Groups Only", callback_data="bc_groups")],
            [InlineKeyboardButton("⬅ Back to Dashboard", callback_data="adm_back")]
        ]
        await query.edit_message_text("Select Mailing Broadcast Target:\nChoose where you want the broadcast message to be delivered:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_back":
        keyboard = [
            [InlineKeyboardButton("📬 Mailing", callback_data="adm_mailing"), InlineKeyboardButton("📊 Statistics", callback_data="adm_stats")],
            [InlineKeyboardButton("🚫 Banned Words", callback_data="adm_banned_words"), InlineKeyboardButton("💬 Custom Replies", callback_data="adm_custom_replies")],
            [InlineKeyboardButton("✖ Close Panel", callback_data="adm_close")]
        ]
        await query.edit_message_text("Administrator Control Panel\nSelect an action from the options below:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "adm_stats":
        users_count = len(db.get_all_users())
        groups_count = len(db.get_all_groups())
        await query.edit_message_text(f"Statistics:\n\nTotal Registered Users: {users_count}\nTotal Groups: {groups_count}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅ Back", callback_data="adm_back")]]))

    elif data == "adm_banned_words":
        user_states[user.id] = {"action": "adding_banned_word"}
        words = ", ".join(db.get_banned_words()) or "None"
        await query.edit_message_text(f"Current Banned Words:\n{words}\n\nSend the word you want to add to blacklist:")

    elif data == "adm_custom_replies":
        user_states[user.id] = {"action": "adding_custom_reply_trigger"}
        await query.edit_message_text("Set Custom Auto-Reply:\n\nStep 1: Send the trigger keyword (e.g. 'pricing', 'support'):")

    elif data.startswith("bc_"):
        target_type = data.replace("bc_", "")
        user_states[user.id] = {"action": "broadcast_waiting", "target": target_type}
        await query.edit_message_text("Please send the message text you want to broadcast:")

    elif data == "adm_close":
        await query.message.delete()

# ----------------- Private Message Text Handler (Forms & Admin Input) ----------------- #

async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    if user.id not in user_states:
        return

    state = user_states[user.id]

    if state["action"] == "submitting_appeal":
        chat_id = state["chat_id"]
        if OWNER_ID:
            await context.bot.send_message(
                OWNER_ID,
                f"New Appeal Received:\nUser: {user.first_name} (@{user.username}) [ID: {user.id}]\nGroup ID: {chat_id}\n\nAppeal:\n{text}"
            )
        await update.message.reply_text("Your appeal has been submitted to admins.")
        del user_states[user.id]

    elif state["action"] == "adding_banned_word":
        db.add_banned_word(text)
        await update.message.reply_text(f"Word '{text}' added to banned words blacklist.")
        del user_states[user.id]

    elif state["action"] == "adding_custom_reply_trigger":
        user_states[user.id] = {"action": "adding_custom_reply_text", "trigger": text}
        await update.message.reply_text(f"Trigger set to '{text}'.\n\nStep 2: Send the reply message text:")

    elif state["action"] == "adding_custom_reply_text":
        user_states[user.id]["reply_text"] = text
        user_states[user.id]["action"] = "adding_custom_reply_button"
        await update.message.reply_text("Step 3: If you want to add an inline button, send format: `Button Name | https://link.com`\nOr send 'skip' for no button.")

    elif state["action"] == "adding_custom_reply_button":
        trigger = user_states[user.id]["trigger"]
        reply_txt = user_states[user.id]["reply_text"]
        btn_name, btn_url = None, None

        if text.lower() != "skip" and "|" in text:
            parts = text.split("|")
            btn_name = parts[0].strip()
            btn_url = parts[1].strip()

        db.add_custom_reply(trigger, reply_txt, btn_name, btn_url)
        await update.message.reply_text("Custom Auto-Reply saved successfully.")
        del user_states[user.id]

    elif state["action"] == "broadcast_waiting":
        target = state["target"]
        targets = []
        if target in ["users", "both"]:
            targets.extend(db.get_all_users())
        if target in ["groups", "both"]:
            targets.extend(db.get_all_groups())

        sent = 0
        for tid in targets:
            try:
                await context.bot.send_message(tid, text)
                sent += 1
            except Exception:
                pass

        await update.message.reply_text(f"Broadcast completed. Delivered to {sent} destinations.")
        del user_states[user.id]

# ----------------- App Initialization ----------------- #

def main():
    db.init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    bot_app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    bot_app.add_handler(CommandHandler("start", cmd_start, filters=filters.ChatType.PRIVATE))
    bot_app.add_handler(CommandHandler("admin", cmd_admin, filters=filters.ChatType.PRIVATE))
    bot_app.add_handler(CommandHandler("warn", cmd_warn, filters=filters.ChatType.GROUPS))
    bot_app.add_handler(CommandHandler("mute", cmd_mute, filters=filters.ChatType.GROUPS))
    bot_app.add_handler(CommandHandler("ban", cmd_ban, filters=filters.ChatType.GROUPS))

    # Handlers
    bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))
    bot_app.add_handler(MessageHandler(filters.ChatType.GROUPS & (~filters.COMMAND), handle_group_message))
    bot_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (~filters.COMMAND), handle_private_text))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))

    print("Bot is up and listening...")
    bot_app.run_polling()

if __name__ == "__main__":
    main()
