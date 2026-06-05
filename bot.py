import telebot
import sqlite3
import os
import csv
import io
import json
import urllib.request
import base64
from datetime import datetime
from telebot import types

TOKEN = os.environ.get("TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
bot = telebot.TeleBot(TOKEN)

# ── Gemini AI Text ────────────────────────────
def tanya_gemini(pertanyaan, konteks_keuangan=""):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    system = (
        "Kamu adalah asisten keuangan pribadi yang ramah, santai, dan helpful. "
        "Kamu berbicara bahasa Indonesia sehari-hari seperti teman. "
        "Kamu membantu pengguna memahami keuangan mereka, memberi saran hemat, "
        "dan menjawab pertanyaan seputar uang. Jawab singkat, jelas, dan tidak kaku. "
        f"{('Konteks keuangan pengguna: ' + konteks_keuangan) if konteks_keuangan else ''}"
    )
    payload = {"contents": [{"parts": [{"text": f"{system}\n\nPengguna: {pertanyaan}"}]}]}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            result = json.loads(res.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return "Maaf, AI lagi gangguan bentar. Coba lagi ya! 🙏"

# ── Gemini Vision (baca struk) ────────────────
def baca_struk(image_bytes):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = """Kamu adalah asisten keuangan. Analisis struk/nota/bon ini.
Ekstrak informasi dan balas HANYA dalam format JSON seperti ini:
{
  "total": 45000,
  "kategori": "Makan",
  "nama_toko": "Nama toko/restoran",
  "item_utama": "deskripsi singkat isi struk",
  "tanggal": "tanggal jika ada, atau kosong"
}
Kategori pilihan: Makan, Transportasi, Belanja, Tagihan, Hiburan, Kesehatan, Pendidikan, Lainnya
Jika tidak bisa membaca struk, balas: {"error": "tidak bisa dibaca"}"""

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}}
            ]
        }]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            result = json.loads(res.read())
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

def get_konteks(user_id):
    rows = get_summary(user_id)
    if not rows:
        return ""
    total_in = sum(amt for t, _, amt in rows if t == "in")
    total_out = sum(amt for t, _, amt in rows if t == "out")
    detail = ", ".join(f"{cat} Rp{amt:,.0f}" for _, cat, amt in rows if _ == "out")
    return f"Bulan ini pemasukan Rp{total_in:,.0f}, pengeluaran Rp{total_out:,.0f}. Detail: {detail}."

# ── Database ──────────────────────────────────
def init_db():
    conn = sqlite3.connect("money.db")
    conn.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, type TEXT, amount REAL,
        category TEXT, note TEXT, date TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, category TEXT, amount REAL, month TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, type TEXT, person TEXT,
        amount REAL, note TEXT, status TEXT DEFAULT 'unpaid', date TEXT)""")
    conn.commit()
    conn.close()

def add_transaction(user_id, tipe, amount, category, note):
    conn = sqlite3.connect("money.db")
    conn.execute("INSERT INTO transactions VALUES (NULL,?,?,?,?,?,?)",
        (user_id, tipe, amount, category, note, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_summary(user_id):
    conn = sqlite3.connect("money.db")
    month = datetime.now().strftime("%Y-%m")
    rows = conn.execute("""SELECT type, category, SUM(amount) FROM transactions
        WHERE user_id=? AND date LIKE ? GROUP BY type, category""",
        (user_id, f"%{month}%")).fetchall()
    conn.close()
    return rows

def get_history(user_id, limit=10):
    conn = sqlite3.connect("money.db")
    rows = conn.execute("""SELECT id, type, amount, category, note, date
        FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?""",
        (user_id, limit)).fetchall()
    conn.close()
    return rows

def delete_transaction(tid, user_id):
    conn = sqlite3.connect("money.db")
    conn.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tid, user_id))
    conn.commit()
    conn.close()

def get_all_transactions(user_id):
    conn = sqlite3.connect("money.db")
    rows = conn.execute("""SELECT type, amount, category, note, date
        FROM transactions WHERE user_id=? ORDER BY date DESC""", (user_id,)).fetchall()
    conn.close()
    return rows

def set_budget(user_id, category, amount):
    conn = sqlite3.connect("money.db")
    month = datetime.now().strftime("%Y-%m")
    conn.execute("DELETE FROM budgets WHERE user_id=? AND category=? AND month=?", (user_id, category, month))
    conn.execute("INSERT INTO budgets VALUES (NULL,?,?,?,?)", (user_id, category, amount, month))
    conn.commit()
    conn.close()

def get_budgets(user_id):
    conn = sqlite3.connect("money.db")
    month = datetime.now().strftime("%Y-%m")
    rows = conn.execute("""SELECT b.category, b.amount, COALESCE(SUM(t.amount),0)
        FROM budgets b LEFT JOIN transactions t ON t.user_id=b.user_id
        AND t.category=b.category AND t.type='out' AND t.date LIKE ?
        WHERE b.user_id=? AND b.month=? GROUP BY b.category, b.amount""",
        (f"%{month}%", user_id, month)).fetchall()
    conn.close()
    return rows

def add_debt(user_id, tipe, person, amount, note):
    conn = sqlite3.connect("money.db")
    conn.execute("INSERT INTO debts VALUES (NULL,?,?,?,?,?,'unpaid',?)",
        (user_id, tipe, person, amount, note, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_debts(user_id, status="unpaid"):
    conn = sqlite3.connect("money.db")
    rows = conn.execute("""SELECT id, type, person, amount, note, date
        FROM debts WHERE user_id=? AND status=? ORDER BY id DESC""",
        (user_id, status)).fetchall()
    conn.close()
    return rows

def pay_debt(did, user_id):
    conn = sqlite3.connect("money.db")
    conn.execute("UPDATE debts SET status='paid' WHERE id=? AND user_id=?", (did, user_id))
    conn.commit()
    conn.close()

# ── State ─────────────────────────────────────
user_state = {}
ai_mode = set()
struk_pending = {}

# ── Keyboards ─────────────────────────────────
def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("➕ Pemasukan", "➖ Pengeluaran")
    kb.row("📊 Rekap Bulan Ini", "📜 Riwayat")
    kb.row("🎯 Budget", "💸 Hutang/Piutang")
    kb.row("📤 Export CSV", "🗑️ Hapus Transaksi")
    kb.row("📷 Scan Struk", "🤖 Tanya AI Keuangan")
    return kb

def cat_keyboard(tipe):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    cats = ["Gaji","Freelance","Investasi","Bonus","Lainnya"] if tipe == "in" else \
           ["Makan","Transportasi","Belanja","Tagihan","Hiburan","Kesehatan","Pendidikan","Lainnya"]
    for i in range(0, len(cats), 2):
        kb.row(*cats[i:i+2])
    return kb

def confirm_struk_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("✅ Simpan", "✏️ Edit Nominal", "❌ Batal")
    return kb

def skip_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("skip")
    return kb

def exit_ai_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("❌ Keluar dari AI Chat")
    return kb

# ── Handlers ──────────────────────────────────
@bot.message_handler(commands=["start","help"])
def start(msg):
    bot.send_message(msg.chat.id,
        "👋 Halo! Aku *Money Tracker* dengan AI! 🤖\n\n"
        "💰 Catat pemasukan & pengeluaran\n"
        "📷 *Scan struk* — foto struk langsung tercatat!\n"
        "🎯 Set budget per kategori\n"
        "💸 Catat hutang & piutang\n"
        "📤 Export data ke CSV\n"
        "🤖 Tanya AI soal keuangan kamu!\n\n"
        "Pilih menu di bawah:",
        parse_mode="Markdown", reply_markup=main_menu())

# ── SCAN STRUK ────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📷 Scan Struk")
def scan_struk_menu(msg):
    ai_mode.discard(msg.chat.id)
    user_state.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id,
        "📷 *Scan Struk*\n\n"
        "Kirim foto struk/nota/bon kamu sekarang!\n"
        "AI akan otomatis membaca total & kategorinya 🤖",
        parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(content_types=["photo"])
def handle_photo(msg):
    uid = msg.chat.id
    bot.send_message(uid, "📷 Sedang membaca struk... tunggu sebentar! 🔍")
    bot.send_chat_action(uid, "typing")

    try:
        file_id = msg.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        with urllib.request.urlopen(file_url) as r:
            image_bytes = r.read()

        hasil = baca_struk(image_bytes)

        if "error" in hasil:
            bot.send_message(uid,
                "❌ Gagal membaca struk. Pastikan foto jelas dan cukup terang ya!\n"
                "Coba foto ulang dengan pencahayaan yang lebih baik.",
                reply_markup=main_menu())
            return

        total = hasil.get("total", 0)
        kategori = hasil.get("kategori", "Lainnya")
        toko = hasil.get("nama_toko", "-")
        item = hasil.get("item_utama", "-")

        struk_pending[uid] = {
            "amount": total,
            "category": kategori,
            "note": f"{toko} - {item}"
        }

        bot.send_message(uid,
            f"✅ *Struk berhasil dibaca!*\n\n"
            f"🏪 Toko: {toko}\n"
            f"🛍️ Item: {item}\n"
            f"📂 Kategori: {kategori}\n"
            f"💰 Total: *Rp {total:,.0f}*\n\n"
            f"Simpan sebagai pengeluaran?",
            parse_mode="Markdown", reply_markup=confirm_struk_keyboard())

    except Exception as e:
        bot.send_message(uid, "❌ Terjadi kesalahan. Coba lagi ya!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "✅ Simpan" and m.chat.id in struk_pending)
def simpan_struk(msg):
    uid = msg.chat.id
    data = struk_pending.pop(uid)
    add_transaction(uid, "out", data["amount"], data["category"], data["note"])
    bot.send_message(uid,
        f"✅ Pengeluaran *Rp {data['amount']:,.0f}* ({data['category']}) tersimpan!",
        parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "✏️ Edit Nominal" and m.chat.id in struk_pending)
def edit_struk(msg):
    uid = msg.chat.id
    user_state[uid] = {"step": "struk_edit_amount"}
    bot.send_message(uid, "💰 Masukkan nominal yang benar (Rp):",
                     reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "❌ Batal" and m.chat.id in struk_pending)
def batal_struk(msg):
    struk_pending.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id, "❌ Dibatalkan.", reply_markup=main_menu())

# ── MENU LAINNYA ──────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ Pemasukan")
def pemasukan(msg):
    ai_mode.discard(msg.chat.id)
    user_state[msg.chat.id] = {"type": "in", "step": "amount"}
    bot.send_message(msg.chat.id, "💰 Masukkan jumlah pemasukan (Rp):",
                     reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "➖ Pengeluaran")
def pengeluaran(msg):
    ai_mode.discard(msg.chat.id)
    user_state[msg.chat.id] = {"type": "out", "step": "amount"}
    bot.send_message(msg.chat.id, "💸 Masukkan jumlah pengeluaran (Rp):",
                     reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "📊 Rekap Bulan Ini")
def rekap(msg):
    ai_mode.discard(msg.chat.id)
    rows = get_summary(msg.chat.id)
    budgets = get_budgets(msg.chat.id)
    budget_dict = {b[0]: (b[1], b[2]) for b in budgets}
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
            if cat in budget_dict:
                limit, spent = budget_dict[cat]
                pct = (amt/limit*100) if limit > 0 else 0
                warn = "⚠️" if pct >= 80 else "✅"
                lines.append(f"  {warn} {cat}: Rp {amt:,.0f} / {limit:,.0f} ({pct:.0f}%)")
            else:
                lines.append(f"  {cat}: Rp {amt:,.0f}")
            total_out += amt
    lines.append(f"  *Total: Rp {total_out:,.0f}*\n")
    sisa = total_in - total_out
    emoji = "✅" if sisa >= 0 else "⚠️"
    lines.append(f"{emoji} *Saldo: Rp {sisa:,.0f}*")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "📜 Riwayat")
def riwayat(msg):
    ai_mode.discard(msg.chat.id)
    rows = get_history(msg.chat.id)
    if not rows:
        bot.send_message(msg.chat.id, "📭 Belum ada transaksi.", reply_markup=main_menu())
        return
    lines = ["📜 *10 Transaksi Terakhir*\n"]
    for tid, tipe, amt, cat, note, date in rows:
        icon = "💚" if tipe == "in" else "❤️"
        lines.append(f"{icon} *Rp {amt:,.0f}* — {cat}\n   {note or '-'} · {date}\n   ID: `{tid}`")
    lines.append("\n_Gunakan 🗑️ Hapus Transaksi untuk menghapus_")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🗑️ Hapus Transaksi")
def hapus_menu(msg):
    ai_mode.discard(msg.chat.id)
    user_state[msg.chat.id] = {"step": "delete_id"}
    bot.send_message(msg.chat.id,
        "🗑️ Masukkan ID transaksi yang mau dihapus\n_(lihat ID di 📜 Riwayat)_",
        parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.text == "🎯 Budget")
def budget_menu(msg):
    ai_mode.discard(msg.chat.id)
    rows = get_budgets(msg.chat.id)
    lines = ["🎯 *Budget Bulan Ini*\n"]
    if rows:
        for cat, limit, spent in rows:
            pct = (spent/limit*100) if limit > 0 else 0
            warn = "⚠️" if pct >= 80 else "✅"
            lines.append(f"{warn} *{cat}*\n   Dipakai: Rp {spent:,.0f} / {limit:,.0f}\n   Sisa: Rp {limit-spent:,.0f} ({pct:.0f}%)")
    else:
        lines.append("Belum ada budget. Ketik /setbudget untuk set!")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(commands=["setbudget"])
def set_budget_cmd(msg):
    ai_mode.discard(msg.chat.id)
    user_state[msg.chat.id] = {"step": "budget_category"}
    bot.send_message(msg.chat.id, "🎯 Pilih kategori budget:", reply_markup=cat_keyboard("out"))

@bot.message_handler(func=lambda m: m.text == "💸 Hutang/Piutang")
def debt_menu(msg):
    ai_mode.discard(msg.chat.id)
    hutang = get_debts(msg.chat.id, "unpaid")
    total_hutang = sum(d[3] for d in hutang if d[1] == "hutang")
    total_piutang = sum(d[3] for d in hutang if d[1] == "piutang")
    lines = ["💸 *Hutang & Piutang*\n"]
    lines.append("*🔴 Hutang Saya*")
    hl = [d for d in hutang if d[1] == "hutang"]
    if hl:
        for did, _, person, amt, note, date in hl:
            lines.append(f"  👤 {person}: Rp {amt:,.0f}\n   {note or '-'} · ID: `{did}`")
    else:
        lines.append("  Tidak ada hutang 🎉")
    lines.append(f"\n*Total hutang: Rp {total_hutang:,.0f}*\n")
    lines.append("*🟢 Piutang Saya*")
    pl = [d for d in hutang if d[1] == "piutang"]
    if pl:
        for did, _, person, amt, note, date in pl:
            lines.append(f"  👤 {person}: Rp {amt:,.0f}\n   {note or '-'} · ID: `{did}`")
    else:
        lines.append("  Tidak ada piutang")
    lines.append(f"\n*Total piutang: Rp {total_piutang:,.0f}*\n")
    lines.append("_/tambah\_hutang — catat baru_\n_/lunas [ID] — tandai lunas_")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_menu())

@bot.message_handler(commands=["tambah_hutang"])
def tambah_hutang(msg):
    ai_mode.discard(msg.chat.id)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("💰 Saya yang Hutang", "💵 Saya yang Piutang")
    user_state[msg.chat.id] = {"step": "debt_type"}
    bot.send_message(msg.chat.id, "💸 Pilih jenis:", reply_markup=kb)

@bot.message_handler(commands=["lunas"])
def lunas_cmd(msg):
    parts = msg.text.split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Format: /lunas [ID]\nContoh: /lunas 3")
        return
    try:
        pay_debt(int(parts[1]), msg.chat.id)
        bot.send_message(msg.chat.id, f"✅ Hutang/piutang ID {parts[1]} sudah lunas!", reply_markup=main_menu())
    except:
        bot.send_message(msg.chat.id, "❌ ID tidak valid.")

@bot.message_handler(func=lambda m: m.text == "📤 Export CSV")
def export_csv(msg):
    ai_mode.discard(msg.chat.id)
    rows = get_all_transactions(msg.chat.id)
    if not rows:
        bot.send_message(msg.chat.id, "📭 Belum ada transaksi.", reply_markup=main_menu())
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Tipe","Jumlah","Kategori","Catatan","Tanggal"])
    for r in rows:
        writer.writerow(["Pemasukan" if r[0]=="in" else "Pengeluaran", r[1], r[2], r[3] or "", r[4]])
    output.seek(0)
    filename = f"money_tracker_{datetime.now().strftime('%Y%m%d')}.csv"
    bot.send_document(msg.chat.id,
        (filename, output.getvalue().encode("utf-8-sig")),
        caption="📤 Data transaksi kamu!", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == "🤖 Tanya AI Keuangan")
def ai_chat(msg):
    user_state.pop(msg.chat.id, None)
    ai_mode.add(msg.chat.id)
    bot.send_message(msg.chat.id,
        "🤖 *Halo! Aku AI asisten keuangan kamu!*\n\n"
        "Tanya apa aja:\n"
        "• _Pengeluaranku wajar ga?_\n"
        "• _Gimana cara nabung lebih hemat?_\n"
        "• _Worth it ga beli HP 5 juta?_\n\n"
        "Ketik pertanyaanmu! 👇",
        parse_mode="Markdown", reply_markup=exit_ai_keyboard())

@bot.message_handler(func=lambda m: m.text == "❌ Keluar dari AI Chat")
def exit_ai(msg):
    ai_mode.discard(msg.chat.id)
    bot.send_message(msg.chat.id, "Oke, balik ke menu utama! 😊", reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.chat.id in ai_mode)
def handle_ai(msg):
    bot.send_chat_action(msg.chat.id, "typing")
    jawaban = tanya_gemini(msg.text, get_konteks(msg.chat.id))
    bot.send_message(msg.chat.id, f"🤖 {jawaban}", reply_markup=exit_ai_keyboard())

# ── INPUT HANDLER ─────────────────────────────
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
            bot.send_message(uid, "❌ Angka tidak valid. Contoh: 50000")

    elif step == "category":
        state["category"] = msg.text
        state["step"] = "note"
        bot.send_message(uid, "📝 Tambah catatan? (atau 'skip'):", reply_markup=skip_keyboard())

    elif step == "note":
        note = "" if msg.text.lower() == "skip" else msg.text
        add_transaction(uid, state["type"], state["amount"], state["category"], note)
        tipe_str = "Pemasukan" if state["type"] == "in" else "Pengeluaran"
        warning = ""
        if state["type"] == "out":
            for cat, limit, spent in get_budgets(uid):
                if cat == state["category"] and limit > 0:
                    pct = spent/limit*100
                    if pct >= 100:
                        warning = f"\n\n⚠️ *Budget {cat} sudah melebihi limit!*"
                    elif pct >= 80:
                        warning = f"\n\n⚠️ Budget {cat} sudah {pct:.0f}% terpakai!"
        bot.send_message(uid,
            f"✅ *{tipe_str}* Rp {state['amount']:,.0f} ({state['category']}) tersimpan!{warning}",
            parse_mode="Markdown", reply_markup=main_menu())
        del user_state[uid]

    elif step == "struk_edit_amount":
        try:
            amt = float(msg.text.replace(".", "").replace(",", "."))
            struk_pending[uid]["amount"] = amt
            data = struk_pending.pop(uid)
            add_transaction(uid, "out", data["amount"], data["category"], data["note"])
            bot.send_message(uid,
                f"✅ Pengeluaran *Rp {data['amount']:,.0f}* ({data['category']}) tersimpan!",
                parse_mode="Markdown", reply_markup=main_menu())
            del user_state[uid]
        except:
            bot.send_message(uid, "❌ Angka tidak valid. Coba lagi:")

    elif step == "delete_id":
        try:
            delete_transaction(int(msg.text), uid)
            bot.send_message(uid, f"✅ Transaksi berhasil dihapus!", reply_markup=main_menu())
        except:
            bot.send_message(uid, "❌ ID tidak valid.")
        del user_state[uid]

    elif step == "budget_category":
        state["budget_cat"] = msg.text
        state["step"] = "budget_amount"
        bot.send_message(uid, f"💰 Masukkan limit budget untuk *{msg.text}* (Rp):",
                         parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())

    elif step == "budget_amount":
        try:
            amt = float(msg.text.replace(".", "").replace(",", "."))
            set_budget(uid, state["budget_cat"], amt)
            bot.send_message(uid,
                f"✅ Budget *{state['budget_cat']}* diset Rp {amt:,.0f}/bulan!",
                parse_mode="Markdown", reply_markup=main_menu())
            del user_state[uid]
        except:
            bot.send_message(uid, "❌ Angka tidak valid.")

    elif step == "debt_type":
        state["debt_type"] = "hutang" if msg.text == "💰 Saya yang Hutang" else "piutang"
        state["step"] = "debt_person"
        bot.send_message(uid, "👤 Nama orang/pihak terkait:", reply_markup=types.ReplyKeyboardRemove())

    elif step == "debt_person":
        state["debt_person"] = msg.text
        state["step"] = "debt_amount"
        bot.send_message(uid, "💰 Jumlah (Rp):")

    elif step == "debt_amount":
        try:
            amt = float(msg.text.replace(".", "").replace(",", "."))
            state["debt_amount"] = amt
            state["step"] = "debt_note"
            bot.send_message(uid, "📝 Catatan? (atau 'skip'):", reply_markup=skip_keyboard())
        except:
            bot.send_message(uid, "❌ Angka tidak valid.")

    elif step == "debt_note":
        note = "" if msg.text.lower() == "skip" else msg.text
        add_debt(uid, state["debt_type"], state["debt_person"], state["debt_amount"], note)
        tipe_str = "Hutang" if state["debt_type"] == "hutang" else "Piutang"
        bot.send_message(uid,
            f"✅ *{tipe_str}* Rp {state['debt_amount']:,.0f} ke/dari *{state['debt_person']}* tersimpan!\n\nGunakan /lunas [ID] kalau sudah lunas.",
            parse_mode="Markdown", reply_markup=main_menu())
        del user_state[uid]

init_db()
print("Bot berjalan...")
bot.polling(none_stop=True)
