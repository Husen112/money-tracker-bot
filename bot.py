import telebot
import sqlite3
import os
from datetime import datetime
from telebot import types

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)

def init_db():
    conn = sqlite3.connect("money.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            category TEXT,
            note TEXT,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_transaction(user_id, tipe, amount, category, note):
    conn = sqlite3.connect("money.db")
    conn.execute("INSERT INTO transactions VALUES (NULL,?,?,?,?,?,?)",
        (user_id, tipe, amount, category, note,
         datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_summary(user_id):
    conn = sqlite3.connect("money.db")
    month = datetime.now().strftime("%Y-%m")
    rows = conn.execute("""
        SELECT type, category, SUM(amount)
        FROM transactions
        WHERE user_id=? AND date LIKE ?
        GROUP BY type, category
    """, (user_id, f"%{month}%")).fetchall()
    conn.close()
    return rows

def get_history(user_id, limit=10):
    conn = sqlite3.connect("money.db")
    rows = conn.execute("""
        SELECT type, amount, category, note, date
        FROM transactions WHERE user_id=?
        ORDER BY id DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return rows

user_state = {}

def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Pemasukan", "➖ Pengeluaran")
    kb.row("📊 Rekap Bulan Ini", "📜 Riwayat")
    return kb

def cat_keyboard(tipe):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if tipe == "in":
        cats = ["Gaji", "Freelance", "Investasi", "Lainnya"]
    else:
        cats = ["Makan", "Transportasi", "Belanja", "Tagihan", "Hiburan", "Kesehatan", "Lainnya"]
    for i in range(0, len(cats), 2):
        kb.row(*cats[i:i+2])
    return kb

@bot.message_handler(commands=["start", "help"])
def start(msg):
    bot.send_message(msg.chat.id,
        "👋 Selamat datang di *Money Tracker*!\n\n"
        "Pilih menu di bawah untuk mulai mencatat keuanganmu.",
        parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "➕ Pemasukan")
def pemasukan(msg):
    user_state[msg.chat.id] = {"type": "in", "step": "amount"}
    bot.send_message(msg.chat.id, "💰 Masukkan jumlah pemasukan (Rp):",
                     reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "➖ Pengeluaran")
def pengeluaran(msg):
    user_state[msg.chat.id] = {"type": "out", "step": "amount"}
    bot.send_message(msg.chat.id, "💸 Masukkan jumlah pengeluaran (Rp):",
                     reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "📊 Rekap Bulan Ini")
def rekap(msg):
    rows = get_summary(msg.chat.id)
    if not rows:
        bot.send_message(msg.chat.id, "📭 Belum ada transaksi bulan ini.", reply_markup=main_menu())
        return
    total_in = total_out = 0
    lines = [f"📊 *Rekap {datetime.now().strftime('%B %Y')}*\n"]
    lines.append("*💚 PEMASUKAN*")
    for tipe, cat, amt in rows:
        if tipe == "in":
            lines.append(f"  {cat}: Rp {amt:,.0f}")
            total_in += amt
    lines.append(f"  *Total: Rp {total_in:,.0f}*\n")
    lines.append("*❤️ PENGELUARAN*")
    for tipe, cat, amt in rows:
        if tipe == "out":
            lines.append(f"  {cat}: Rp {amt:,.0f}")
            total_out += amt
    lines.append(f"  *Total: Rp {total_out:,.0f}*\n")
    sisa = total_in - total_out
    emoji = "✅" if sisa >= 0 else "⚠️"
    lines.append(f"{emoji} *Saldo: Rp {sisa:,.0f}*")
    bot.send_message(msg.chat.id, "\n".join(lines),
                     parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "📜 Riwayat")
def riwayat(msg):
    rows = get_history(msg.chat.id)
    if not rows:
        bot.send_message(msg.chat.id, "📭 Belum ada transaksi.", reply_markup=main_menu())
        return
    lines = ["📜 *10 Transaksi Terakhir*\n"]
    for tipe, amt, cat, note, date in rows:
        icon = "💚" if tipe == "in" else "❤️"
        lines.append(f"{icon} *Rp {amt:,.0f}* — {cat}\n   {note or '-'} · {date}")
    bot.send_message(msg.chat.id, "\n".join(lines),
                     parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.chat.id in user_state)
def handle_input(msg):
    uid = msg.chat.id
    state = user_state[uid]
    step = state["step"]

    if step == "amount":
        try:
            amt = float(msg.text.replace(".", "").replace(",", "."))
            state["amount"] = amt
            state["step"] = "category"
            bot.send_message(uid, "📂 Pilih kategori:", reply_markup=cat_keyboard(state["type"]))
        except:
            bot.send_message(uid, "❌ Angka tidak valid. Coba lagi (contoh: 50000):")

    elif step == "category":
        state["category"] = msg.text
        state["step"] = "note"
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("skip")
        bot.send_message(uid, "📝 Tambah catatan? (atau tekan 'skip'):", reply_markup=kb)

    elif step == "note":
        note = "" if msg.text.lower() == "skip" else msg.text
        add_transaction(uid, state["type"], state["amount"], state["category"], note)
        tipe_str = "Pemasukan" if state["type"] == "in" else "Pengeluaran"
        bot.send_message(uid,
            f"✅ *{tipe_str}* Rp {state['amount']:,.0f} ({state['category']}) tersimpan!",
            parse_mode="Markdown", reply_markup=main_menu())
        del user_state[uid]

init_db()
print("Bot berjalan...")
bot.polling(none_stop=True)
