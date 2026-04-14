"""
PIERO AVIATOR BOT - Lisans Sunucusu
"""
from flask import Flask, request, jsonify
import sqlite3, os, hashlib, datetime

app = Flask(__name__)

ADMIN_PASSWORD = "piero2024admin"
import pathlib

# Railway'de kalıcı veri için /data volume kullan
# Yoksa script dizinini kullan
_data_dir = pathlib.Path("/data") if pathlib.Path("/data").exists() else pathlib.Path(".")
DB_PATH = str(_data_dir / "licenses.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key          TEXT PRIMARY KEY,
            hwid         TEXT DEFAULT NULL,
            activated    INTEGER DEFAULT 0,
            activated_at TEXT DEFAULT NULL,
            last_opened  TEXT DEFAULT NULL,
            last_runtime TEXT DEFAULT NULL,
            last_profit  TEXT DEFAULT NULL,
            total_runs   INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            note         TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key        TEXT NOT NULL,
            opened_at  TEXT,
            duration   TEXT,
            profit     REAL DEFAULT 0,
            logged_at  TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_hwid(hwid):
    return hashlib.sha256(hwid.encode()).hexdigest()[:32]

def validate_key_format(key):
    parts = key.upper().split("-")
    if len(parts) != 4 or parts[0] != "PIERO":
        return False
    try:
        a, b, c = int(parts[1]), int(parts[2]), int(parts[3])
        return (a * 17 + b * 31) % 10000 == c
    except:
        return False

# ── AKTİVASYON ──────────────────────────────────────────────────
@app.route("/activate", methods=["POST"])
def activate():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key",  "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()
    if not key or not hwid:
        return jsonify({"ok": False, "msg": "Eksik parametre"}), 400
    if not validate_key_format(key):
        return jsonify({"ok": False, "msg": "Geçersiz lisans formatı"}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "msg": "Lisans bulunamadı"}), 404
    hashed = hash_hwid(hwid)
    if row["activated"] == 1:
        if row["hwid"] == hashed:
            conn.close()
            return jsonify({"ok": True, "msg": "Giriş yapıldı"})
        conn.close()
        return jsonify({"ok": False, "msg": "Bu lisans başka bir bilgisayarda aktive edilmiş"}), 403
    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    conn.execute("UPDATE licenses SET hwid=?, activated=1, activated_at=? WHERE key=?", (hashed, now, key))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": "Lisans aktive edildi"})

# ── KONTROL ─────────────────────────────────────────────────────
@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key",  "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()
    if not key or not hwid:
        return jsonify({"ok": False}), 400
    conn   = get_db()
    row    = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row or row["activated"] != 1:
        return jsonify({"ok": False, "msg": "Geçersiz lisans"}), 403
    if row["hwid"] != hash_hwid(hwid):
        return jsonify({"ok": False, "msg": "Bu bilgisayara ait değil"}), 403
    return jsonify({"ok": True})

# ── LOG (kapanışta çalışma süresi) ──────────────────────────────
@app.route("/log", methods=["POST"])
def log_event():
    data     = request.get_json(silent=True) or {}
    key      = str(data.get("key",      "")).upper().strip()
    hwid     = str(data.get("hwid",     "")).strip()
    duration = str(data.get("duration", "")).strip()
    opened   = str(data.get("opened_at","")).strip()
    profit   = float(data.get("profit", 0))
    if not key:
        return jsonify({"ok": False}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    if not row or row["activated"] != 1 or row["hwid"] != hash_hwid(hwid):
        conn.close()
        return jsonify({"ok": False}), 403
    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    profit_str = ("+" if profit >= 0 else "") + str(round(profit, 2)) + " TL"
    conn.execute("""
        UPDATE licenses
        SET last_opened=?, last_runtime=?, last_profit=?,
            total_runs=total_runs+1, total_profit=total_profit+?
        WHERE key=?
    """, (opened, duration, profit_str, profit, key))
    conn.execute("""
        INSERT INTO sessions (key, opened_at, duration, profit, logged_at)
        VALUES (?, ?, ?, ?, ?)
    """, (key, opened, duration, profit, now))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── ADMİN: Lisans Ekle ──────────────────────────────────────────
@app.route("/admin/add", methods=["POST"])
def admin_add():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    keys = data.get("keys", [])
    note = data.get("note", "")
    conn = get_db()
    added, skipped = [], []
    for key in keys:
        key = key.upper().strip()
        if not validate_key_format(key):
            skipped.append(key + " (format hatası)")
            continue
        if conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone():
            skipped.append(key + " (zaten var)")
            continue
        conn.execute("INSERT INTO licenses (key, note) VALUES (?, ?)", (key, note))
        added.append(key)
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "added": added, "skipped": skipped})

# ── ADMİN: Listele ──────────────────────────────────────────────
@app.route("/admin/list", methods=["GET"])
def admin_list():
    if request.args.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM licenses ORDER BY activated_at DESC").fetchall()
    conn.close()
    result = [{
        "key":          r["key"],
        "activated":    bool(r["activated"]),
        "activated_at": r["activated_at"],
        "last_opened":  r["last_opened"],
        "last_runtime": r["last_runtime"],
        "last_profit":  r["last_profit"],
        "total_runs":   r["total_runs"],
        "total_profit": round(r["total_profit"] or 0, 2),
        "note":         r["note"]
    } for r in rows]
    return jsonify({"ok": True, "total": len(result), "licenses": result})

# ── ADMİN: Sıfırla ──────────────────────────────────────────────
@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    key  = str(data.get("key", "")).upper().strip()
    conn = get_db()
    if not conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone():
        conn.close()
        return jsonify({"ok": False, "msg": "Lisans bulunamadı"}), 404
    conn.execute("UPDATE licenses SET hwid=NULL, activated=0, activated_at=NULL WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": key + " sıfırlandı"})

# ── ADMİN PANELİ ────────────────────────────────────────────────
@app.route("/admin")
def admin_panel():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html")
    if not os.path.exists(html_path):
        return "admin.html bulunamadı.", 404
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
