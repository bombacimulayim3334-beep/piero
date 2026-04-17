"""
PIERO AVIATOR BOT - Lisans Sunucusu
"""
from flask import Flask, request, jsonify
import sqlite3, os, hashlib, datetime, pathlib, json

app = Flask(__name__)

ADMIN_PASSWORD = "piero2024admin"

# Railway /data volume varsa onu kullan (kalıcı), yoksa local
_data_dir = pathlib.Path("/data") if pathlib.Path("/data").exists() else pathlib.Path(".")
DB_PATH = str(_data_dir / "licenses.db")

# ── VERİTABANI ──────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key           TEXT PRIMARY KEY,
            hwid          TEXT DEFAULT NULL,
            activated     INTEGER DEFAULT 0,
            activated_at  TEXT DEFAULT NULL,
            last_opened   TEXT DEFAULT NULL,
            last_runtime  TEXT DEFAULT NULL,
            last_profit   TEXT DEFAULT NULL,
            total_runs    INTEGER DEFAULT 0,
            total_profit  REAL DEFAULT 0,
            note          TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            key        TEXT PRIMARY KEY,
            command    TEXT DEFAULT NULL,
            issued_at  TEXT DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS remote_config (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        )
    """)
    # Varsayılan config değerleri
    defaults = [
        ("cashout_multiplier", "1.50"),
        ("message", ""),
        ("strategies", '[{"name":"Strateji 1","bets":"10,40,130,400,1210,3640,10920"},{"name":"Strateji 2","bets":"2,8,26,80,242,728,2186,6560"}]'),
    ]
    for k, v in defaults:
        conn.execute("INSERT OR IGNORE INTO remote_config (key, value) VALUES (?, ?)", (k, v))
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

def hash_hwid(hwid):
    return hashlib.sha256(hwid.encode()).hexdigest()[:32]

def validate_key(key):
    parts = key.upper().split("-")
    if len(parts) != 4 or parts[0] != "PIERO":
        return False
    try:
        a, b, c = int(parts[1]), int(parts[2]), int(parts[3])
        return (a * 17 + b * 31) % 10000 == c
    except:
        return False

# ── AKTİVASYON ──────────────────────────────────────────────────────────────
@app.route("/activate", methods=["POST"])
def activate():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key",  "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()
    if not key or not hwid:
        return jsonify({"ok": False, "msg": "Eksik parametre"}), 400
    if not validate_key(key):
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

# ── KONTROL ─────────────────────────────────────────────────────────────────
@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key",  "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()
    if not key or not hwid:
        return jsonify({"ok": False}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row or row["activated"] != 1:
        return jsonify({"ok": False, "msg": "Geçersiz lisans"}), 403
    if row["hwid"] != hash_hwid(hwid):
        return jsonify({"ok": False, "msg": "Bu bilgisayara ait değil"}), 403
    return jsonify({"ok": True})

# ── LOG (kapanışta süre + kâr) ───────────────────────────────────────────────
@app.route("/log", methods=["POST"])
def log_event():
    data     = request.get_json(silent=True) or {}
    key      = str(data.get("key",       "")).upper().strip()
    hwid     = str(data.get("hwid",      "")).strip()
    duration = str(data.get("duration",  "")).strip()
    opened   = str(data.get("opened_at", "")).strip()
    profit   = float(data.get("profit",  0))
    if not key:
        return jsonify({"ok": False}), 400
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    if not row or row["activated"] != 1 or row["hwid"] != hash_hwid(hwid):
        conn.close()
        return jsonify({"ok": False}), 403
    now        = datetime.datetime.utcnow().isoformat(timespec="seconds")
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

# ── ADMİN: Lisans Ekle ──────────────────────────────────────────────────────
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
        if not validate_key(key):
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

# ── ADMİN: Listele ──────────────────────────────────────────────────────────
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

# ── ADMİN: Lisans Sıfırla (başka bilgisayara taşı) ─────────────────────────
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
    return jsonify({"ok": True, "msg": key + " sıfırlandı (başka bilgisayara aktive edilebilir)"})

# ── ADMİN: İstatistik Sıfırla (kâr, süre, oturum) ─────────────────────────
@app.route("/admin/resetstats", methods=["POST"])
def admin_resetstats():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    key  = str(data.get("key", "")).upper().strip()
    conn = get_db()
    if not conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone():
        conn.close()
        return jsonify({"ok": False, "msg": "Lisans bulunamadı"}), 404
    conn.execute("""
        UPDATE licenses
        SET last_opened=NULL, last_runtime=NULL, last_profit=NULL,
            total_runs=0, total_profit=0
        WHERE key=?
    """, (key,))
    conn.execute("DELETE FROM sessions WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": key + " istatistikleri sıfırlandı"})

# ── ADMİN: Oturum Geçmişi ───────────────────────────────────────────────────
@app.route("/admin/sessions", methods=["GET"])
def admin_sessions():
    if request.args.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    key   = request.args.get("key", "")
    limit = int(request.args.get("limit", 200))
    conn  = get_db()
    if key:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE key=? ORDER BY logged_at DESC LIMIT ?",
            (key.upper(), limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY logged_at DESC LIMIT ?",
            (limit,)).fetchall()
    conn.close()
    result = [{
        "id":        r["id"],
        "key":       r["key"],
        "opened_at": r["opened_at"],
        "duration":  r["duration"],
        "profit":    round(r["profit"] or 0, 2),
        "logged_at": r["logged_at"]
    } for r in rows]
    return jsonify({"ok": True, "total": len(result), "sessions": result})

# ── ADMİN: Yedekle ─────────────────────────────────────────────────────────
@app.route("/admin/export", methods=["GET"])
def admin_export():
    if request.args.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    conn     = get_db()
    licenses = [dict(r) for r in conn.execute("SELECT * FROM licenses").fetchall()]
    sessions = [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
    conn.close()
    return jsonify({"ok": True, "licenses": licenses, "sessions": sessions})

# ── ADMİN: Geri Yükle ───────────────────────────────────────────────────────
@app.route("/admin/import", methods=["POST"])
def admin_import():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    licenses = data.get("licenses", [])
    conn = get_db()
    added, updated = 0, 0
    for lic in licenses:
        existing = conn.execute("SELECT key FROM licenses WHERE key=?", (lic["key"],)).fetchone()
        if existing:
            conn.execute("""
                UPDATE licenses SET hwid=?, activated=?, activated_at=?,
                last_opened=?, last_runtime=?, last_profit=?,
                total_runs=?, total_profit=?, note=?
                WHERE key=?
            """, (lic.get("hwid"), lic.get("activated", 0), lic.get("activated_at"),
                  lic.get("last_opened"), lic.get("last_runtime"), lic.get("last_profit"),
                  lic.get("total_runs", 0), lic.get("total_profit", 0), lic.get("note"), lic["key"]))
            updated += 1
        else:
            conn.execute("""
                INSERT INTO licenses
                (key,hwid,activated,activated_at,last_opened,last_runtime,last_profit,total_runs,total_profit,note)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (lic["key"], lic.get("hwid"), lic.get("activated", 0), lic.get("activated_at"),
                  lic.get("last_opened"), lic.get("last_runtime"), lic.get("last_profit"),
                  lic.get("total_runs", 0), lic.get("total_profit", 0), lic.get("note")))
            added += 1
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "added": added, "updated": updated})

# ── KOMUT — Program tarafından çekilir (30sn'de bir) ───────────────────────
@app.route("/command", methods=["POST"])
def get_command():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key",  "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    if not row or row["activated"] != 1 or row["hwid"] != hash_hwid(hwid):
        conn.close()
        return jsonify({"ok": False}), 403
    cmd_row = conn.execute("SELECT command FROM commands WHERE key=?", (key,)).fetchone()
    if not cmd_row or not cmd_row["command"]:
        conn.close()
        return jsonify({"ok": True, "command": None})
    command = cmd_row["command"]
    conn.execute("UPDATE commands SET command=NULL, issued_at=NULL WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "command": command})

# ── ADMİN: Komut Gönder ─────────────────────────────────────────────────────
@app.route("/admin/command", methods=["POST"])
def admin_command():
    data    = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401
    key     = str(data.get("key",     "")).upper().strip()
    command = str(data.get("command", "")).strip()
    conn = get_db()
    if not conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone():
        conn.close()
        return jsonify({"ok": False, "msg": "Lisans bulunamadı"}), 404
    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO commands (key, command, issued_at) VALUES (?, ?, ?)",
        (key, command, now)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": key + " → '" + command + "' komutu gönderildi"})

# ── ADMİN PANELİ ────────────────────────────────────────────────────────────
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
