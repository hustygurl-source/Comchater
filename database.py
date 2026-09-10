import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Users & Groups Storage
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT
        );
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY,
            title TEXT
        );
    ''')
    
    # Warnings Storage
    cur.execute('''
        CREATE TABLE IF NOT EXISTS warnings (
            user_id BIGINT,
            chat_id BIGINT,
            count INT DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        );
    ''')
    
    # Banned Words
    cur.execute('''
        CREATE TABLE IF NOT EXISTS banned_words (
            id SERIAL PRIMARY KEY,
            word TEXT UNIQUE
        );
    ''')
    
    # Custom Auto Replies
    cur.execute('''
        CREATE TABLE IF NOT EXISTS custom_replies (
            id SERIAL PRIMARY KEY,
            trigger TEXT UNIQUE,
            reply_text TEXT,
            btn_name TEXT,
            btn_url TEXT
        );
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

# Database Functions
def add_user(user_id, username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING;", (user_id, username))
    conn.commit()
    cur.close()
    conn.close()

def add_group(chat_id, title):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO groups (chat_id, title) VALUES (%s, %s) ON CONFLICT (chat_id) DO NOTHING;", (chat_id, title))
    conn.commit()
    cur.close()
    conn.close()

def get_warns(user_id, chat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT count FROM warnings WHERE user_id = %s AND chat_id = %s;", (user_id, chat_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else 0

def update_warns(user_id, chat_id, delta):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT count FROM warnings WHERE user_id = %s AND chat_id = %s;", (user_id, chat_id))
    row = cur.fetchone()
    if row:
        new_count = max(0, row[0] + delta)
        cur.execute("UPDATE warnings SET count = %s WHERE user_id = %s AND chat_id = %s;", (new_count, user_id, chat_id))
    else:
        new_count = max(0, delta)
        cur.execute("INSERT INTO warnings (user_id, chat_id, count) VALUES (%s, %s, %s);", (user_id, chat_id, new_count))
    conn.commit()
    cur.close()
    conn.close()
    return new_count

def reset_warns(user_id, chat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM warnings WHERE user_id = %s AND chat_id = %s;", (user_id, chat_id))
    conn.commit()
    cur.close()
    conn.close()

def get_banned_words():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT word FROM banned_words;")
    words = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return words

def add_banned_word(word):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO banned_words (word) VALUES (%s) ON CONFLICT DO NOTHING;", (word.lower().strip(),))
        conn.commit()
    finally:
        cur.close()
        conn.close()

def get_custom_replies():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM custom_replies;")
    replies = cur.fetchall()
    cur.close()
    conn.close()
    return replies

def add_custom_reply(trigger, reply_text, btn_name=None, btn_url=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO custom_replies (trigger, reply_text, btn_name, btn_url)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (trigger) DO UPDATE SET reply_text = EXCLUDED.reply_text, btn_name = EXCLUDED.btn_name, btn_url = EXCLUDED.btn_url;
    ''', (trigger.lower().strip(), reply_text, btn_name, btn_url))
    conn.commit()
    cur.close()
    conn.close()

def get_all_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users;")
    ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return ids

def get_all_groups():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM groups;")
    ids = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return ids
