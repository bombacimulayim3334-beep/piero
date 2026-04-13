"""
PIERO AVIATOR BOT - Lisans Sunucusu
Railway / Render / Heroku'ya deploy edilir.

Endpoints:
  POST /activate  - Lisansı aktive et (ilk kullanım)
  POST /check     - Lisans geçerli mi kontrol et
  POST /admin/add - Yeni lisans ekle (admin şifresi gerekli)
  GET  /admin/list - Tüm lisansları listele (admin şifresi gerekli)
"""

from flask import Flask, request, jsonify
import sqlite3, os, hashlib, datetime

app = Flask(__name__)

# Admin şifresi - deploy etmeden önce değiştir!
ADMIN_PASSWORD = "piero2024admin"
DB_PATH = "licenses.db"

# ---------------------------------------------------------------
#  VERİTABANI
# ---------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



# ---------------------------------------------------------------
#  YARDIMCI
# ---------------------------------------------------------------
def hash_hwid(hwid):
    """HwID'i hash'le - ham değeri saklamıyoruz"""
    return hashlib.sha256(hwid.encode()).hexdigest()[:32]

def validate_key_format(key):
    """PIERO-AAAA-BBBB-CCCC formatını doğrula"""
    parts = key.upper().split("-")
    if len(parts) != 4 or parts[0] != "PIERO":
        return False
    try:
        a, b, c = int(parts[1]), int(parts[2]), int(parts[3])
        return (a * 17 + b * 31) % 10000 == c
    except:
        return False

# ---------------------------------------------------------------
#  AKTİVASYON  (ilk kullanım - lisansı bu bilgisayara bağla)
# ---------------------------------------------------------------
@app.route("/activate", methods=["POST"])
def activate():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key", "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()

    if not key or not hwid:
        return jsonify({"ok": False, "msg": "Eksik parametre"}), 400

    if not validate_key_format(key):
        return jsonify({"ok": False, "msg": "Geçersiz lisans anahtarı formatı"}), 400

    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "msg": "Bu lisans anahtarı sistemde bulunamadı"}), 404

    hashed = hash_hwid(hwid)

    if row["activated"] == 1:
        # Zaten aktive edilmiş — aynı bilgisayar mı?
        if row["hwid"] == hashed:
            conn.close()
            return jsonify({"ok": True, "msg": "Zaten aktive edilmiş, giriş yapıldı"})
        else:
            conn.close()
            return jsonify({"ok": False, "msg": "Bu lisans başka bir bilgisayarda aktive edilmiş"}), 403

    # İlk aktivasyon
    now = datetime.datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE licenses SET hwid=?, activated=1, activated_at=? WHERE key=?",
        (hashed, now, key)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": "Lisans başarıyla aktive edildi"})

# ---------------------------------------------------------------
#  KONTROL  (her program açılışında)
# ---------------------------------------------------------------
@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    key  = str(data.get("key", "")).upper().strip()
    hwid = str(data.get("hwid", "")).strip()

    if not key or not hwid:
        return jsonify({"ok": False, "msg": "Eksik parametre"}), 400

    conn   = get_db()
    row    = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    conn.close()

    if not row or row["activated"] != 1:
        return jsonify({"ok": False, "msg": "Lisans geçersiz veya aktive edilmemiş"}), 403

    hashed = hash_hwid(hwid)
    if row["hwid"] != hashed:
        return jsonify({"ok": False, "msg": "Lisans bu bilgisayara ait değil"}), 403

    return jsonify({"ok": True, "msg": "Lisans geçerli"})

# ---------------------------------------------------------------
#  ADMİN — Lisans Ekle
# ---------------------------------------------------------------
@app.route("/admin/add", methods=["POST"])
def admin_add():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz erişim"}), 401

    keys = data.get("keys", [])
    note = data.get("note", "")
    if not keys:
        return jsonify({"ok": False, "msg": "Anahtar listesi boş"}), 400

    conn    = get_db()
    added   = []
    skipped = []

    for key in keys:
        key = key.upper().strip()
        if not validate_key_format(key):
            skipped.append(key + " (format hatası)")
            continue
        existing = conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone()
        if existing:
            skipped.append(key + " (zaten var)")
            continue
        conn.execute("INSERT INTO licenses (key, note) VALUES (?, ?)", (key, note))
        added.append(key)

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "added": added, "skipped": skipped})

# ---------------------------------------------------------------
#  ADMİN — Lisansları Listele
# ---------------------------------------------------------------
@app.route("/admin/list", methods=["GET"])
def admin_list():
    password = request.args.get("password", "")
    if password != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz erişim"}), 401

    conn = get_db()
    rows = conn.execute("SELECT key, activated, activated_at, note FROM licenses ORDER BY activated_at DESC").fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "key":          r["key"],
            "activated":    bool(r["activated"]),
            "activated_at": r["activated_at"],
            "note":         r["note"]
        })
    return jsonify({"ok": True, "total": len(result), "licenses": result})

# ---------------------------------------------------------------
#  ADMİN — Lisansı Sıfırla (başka bilgisayara taşı)
# ---------------------------------------------------------------
@app.route("/admin/reset", methods=["POST"])
def admin_reset():
    data = request.get_json(silent=True) or {}
    if data.get("password") != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz erişim"}), 401

    key  = str(data.get("key", "")).upper().strip()
    conn = get_db()
    row  = conn.execute("SELECT key FROM licenses WHERE key=?", (key,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"ok": False, "msg": "Lisans bulunamadı"}), 404

    conn.execute("UPDATE licenses SET hwid=NULL, activated=0, activated_at=NULL WHERE key=?", (key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": key + " sıfırlandı, yeniden aktive edilebilir"})

# ---------------------------------------------------------------
#  OTURUM LOGU  (program tarafından çağrılır)
# ---------------------------------------------------------------
@app.route("/log", methods=["POST"])
def log_event():
    data  = request.get_json(silent=True) or {}
    key   = str(data.get("key",    "")).upper().strip()
    hwid  = str(data.get("hwid",   "")).strip()
    event = str(data.get("event",  "")).strip()   # open / close / ping
    detail = str(data.get("detail","")).strip()   # opsiyonel detay

    if not key or not event:
        return jsonify({"ok": False}), 400

    # Lisans geçerli mi kontrol et
    conn = get_db()
    row  = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
    if not row or row["activated"] != 1:
        conn.close()
        return jsonify({"ok": False, "msg": "Geçersiz lisans"}), 403

    hashed = hash_hwid(hwid)
    if row["hwid"] != hashed:
        conn.close()
        return jsonify({"ok": False, "msg": "HwID uyuşmuyor"}), 403

    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO session_logs (key, event, ts, detail) VALUES (?, ?, ?, ?)",
        (key, event, now, detail)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ---------------------------------------------------------------
#  ADMİN — Logları Getir
# ---------------------------------------------------------------
@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    password = request.args.get("password", "")
    key      = request.args.get("key", "")
    limit    = int(request.args.get("limit", 200))

    if password != ADMIN_PASSWORD:
        return jsonify({"ok": False, "msg": "Yetkisiz"}), 401

    conn = get_db()
    if key:
        rows = conn.execute(
            "SELECT * FROM session_logs WHERE key=? ORDER BY ts DESC LIMIT ?",
            (key.upper(), limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM session_logs ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()

    result = [{"id": r["id"], "key": r["key"], "event": r["event"],
               "ts": r["ts"], "detail": r["detail"]} for r in rows]
    return jsonify({"ok": True, "total": len(result), "logs": result})

# Admin paneli serve et
@app.route("/admin")
def admin_panel():
    with open(os.path.join(os.path.dirname(__file__), "admin.html"), "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
