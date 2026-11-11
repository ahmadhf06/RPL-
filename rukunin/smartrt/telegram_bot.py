"""Bot Telegram RUKUNIN: jembatan alarm darurat ke HP warga.

Dua arah, dua-duanya memakai tabel `alarm_darurat` yang sama dengan panel web:

  Telegram -> Web : pesan berisi kata "darurat" / "bahaya" dari chat yang terdaftar menyalakan alarm.
                    Sirene berbunyi di semua browser yang sedang membuka RUKUNIN (lewat js/alarm.js).
  Web -> Telegram : alarm yang dinyalakan / dimatikan dari web dikirim ke semua chat terdaftar,
                    sehingga HP berbunyi walaupun pemiliknya tidak sedang membuka web. Pesannya berupa SATU pesan audio:
                    sirene (MP3) yang bisa langsung diputar + keterangan alarm sebagai teks (nada dering = nada notifikasi Telegram).

Cara bot menerima pesan (TELEGRAM_MODE):
  polling (bawaan) - server RUKUNIN yang menanyakan pesan baru ke Telegram. TIDAK butuh alamat publik / ngrok.
  webhook          - Telegram yang mengirim pesan ke server. Butuh alamat HTTPS publik (TELEGRAM_WEBHOOK_URL).
  off              - bot dimatikan sepenuhnya.

Token bot: diambil dari variabel lingkungan TELEGRAM_BOT_TOKEN atau berkas instance/telegram_token.txt (lihat config.py).
Bila keduanya kosong, dipakai TOKEN_BAWAAN di bawah ini. JANGAN unggah berkas ini ke GitHub/grup selama TOKEN_BAWAAN terisi.
"""
import hashlib
import hmac
import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request

from . import core, ntfy_push

bp = Blueprint("telegram", __name__)

TOKEN_BAWAAN = "9196494779:AAGJryjMvzx-tusQJn4oPzhzdWgTU7ve1a4"                # token dari @BotFather; dipakai hanya bila env / instance/telegram_token.txt kosong
CHAT_ID_BAWAAN = ""                       # Chat ID penerima alarm, pisahkan koma, mis. "123456789, -100987654321" (tambahan dari Pengaturan Sistem)
KATA_DARURAT = ("darurat", "bahaya")      # pesan yang mengandung salah satu kata ini menyalakan alarm
MAKS_UMUR_DETIK = 300                     # pesan lebih tua dari ini (mis. terkirim saat server mati) tidak menyalakan alarm
_STOP = threading.Event()
_THREAD = None
_BOT_USERNAME = "@RUKUNINBOT"             # hanya label di panel; diganti otomatis dengan nama asli setelah getMe berhasil
_AUDIO_CACHE = {}                         # (path, waktu ubah, ukuran) -> file_id Telegram, supaya sirene hanya diunggah sekali


# ---------------------------------------------------------------- API Telegram
def _multipart(payload, berkas):
    """Susun badan permintaan multipart/form-data. berkas = {"audio": (nama_file, isi_bytes, mime)}."""
    batas = "rukunin" + uuid.uuid4().hex
    bagian = []
    for k, v in (payload or {}).items():
        bagian.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (batas, k, v)).encode("utf-8"))
    for k, (nama, isi, mime) in berkas.items():
        kepala = '--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\nContent-Type: %s\r\n\r\n' % (batas, k, nama, mime)
        bagian.append(kepala.encode("utf-8") + isi + b"\r\n")
    bagian.append(("--%s--\r\n" % batas).encode("utf-8"))
    return b"".join(bagian), "multipart/form-data; boundary=%s" % batas


def _api(token, metode, payload=None, timeout=15, berkas=None):
    """Panggil Bot API. Tidak pernah melempar error: kegagalan dikembalikan sebagai {"ok": False, ...}."""
    if berkas:
        data, jenis = _multipart(payload, berkas)
    else:
        data, jenis = json.dumps(payload or {}).encode("utf-8"), "application/json"
    req = urllib.request.Request("https://api.telegram.org/bot%s/%s" % (token, metode), data=data,
                                 headers={"Content-Type": jenis})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error_code": e.code, "description": str(e)}
    except Exception as e:                      # tidak ada internet, timeout, dsb.
        return {"ok": False, "error_code": 0, "description": str(e)}


def _kirim(token, chat_id, teks):
    return _api(token, "sendMessage", {"chat_id": chat_id, "text": teks[:4000], "disable_web_page_preview": True})


def _kirim_dengan_sirene(token, chat_id, teks, audio_path):
    """Kirim keterangan alarm + sirene sebagai SATU pesan audio (satu notifikasi, sirene bisa langsung diputar).
    Bila sirene bukan MP3, tidak ada, atau Telegram menolak, kirim teks biasa agar alarm tetap sampai."""
    if audio_path and audio_path.lower().endswith(".mp3") and os.path.isfile(audio_path):
        try:
            st = os.stat(audio_path)
            kunci = (audio_path, st.st_mtime_ns, st.st_size)
            dasar = {"chat_id": chat_id, "caption": teks[:1000], "title": "Sirene RUKUNIN", "performer": "RUKUNIN"}
            file_id = _AUDIO_CACHE.get(kunci)
            if file_id:
                r = _api(token, "sendAudio", dict(dasar, audio=file_id))
                if not r.get("ok"):
                    _AUDIO_CACHE.pop(kunci, None)
            else:
                with open(audio_path, "rb") as f:
                    isi = f.read()
                r = _api(token, "sendAudio", dasar, timeout=40, berkas={"audio": ("sirene-rukunin.mp3", isi, "audio/mpeg")})
                fid = ((r.get("result") or {}).get("audio") or {}).get("file_id") if r.get("ok") else None
                if fid:
                    _AUDIO_CACHE[kunci] = fid
            if r.get("ok"):
                return r
        except OSError:
            pass
    return _kirim(token, chat_id, teks)


def _kirim_banyak(token, chat_ids, teks, audio=None):
    """Kirim ke banyak chat. Mengembalikan (jumlah_berhasil, daftar_gagal)."""
    berhasil, gagal = 0, []
    for cid in chat_ids:
        r = _kirim_dengan_sirene(token, cid, teks, audio) if audio else _kirim(token, cid, teks)
        if r.get("ok"):
            berhasil += 1
        else:
            gagal.append((cid, r.get("description", "?")))
    for cid, sebab in gagal:
        print("[Telegram] Gagal kirim ke chat %s: %s" % (cid, sebab), flush=True)
    return berhasil, gagal


# ---------------------------------------------------------------- konfigurasi & status
def _token():
    return (current_app.config.get("TELEGRAM_BOT_TOKEN") or "").strip()


def chat_ids():
    """Chat ID penerima/pengirim alarm: gabungan CHAT_ID_BAWAAN, env TELEGRAM_CHAT_IDS dan Pengaturan Sistem (admin)."""
    mentah = "%s,%s,%s" % (CHAT_ID_BAWAAN, current_app.config.get("TELEGRAM_CHAT_IDS") or "",
                           core.get_settings().get("telegram_chat_ids") or "")
    return list(dict.fromkeys(re.findall(r"-?\d{3,20}", mentah)))


def status():
    """Ringkasan untuk panel Alarm Darurat."""
    mode = (current_app.config.get("TELEGRAM_MODE") or "polling").lower()
    return {
        "token_ada": bool(_token()),
        "mode": mode,
        "jumlah_chat": len(chat_ids()),
        "bot": _BOT_USERNAME,
    }


def _webhook_secret(token):
    """Rahasia yang diminta Telegram dikirim di header; diturunkan dari token agar tidak perlu disimpan."""
    return hashlib.sha256(("rukunin-webhook:" + token).encode("utf-8")).hexdigest()[:48]


def _url_panel():
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    return base + "/darurat" if base else ""


# ---------------------------------------------------------------- teks pesan
def teks_alarm_aktif(jenis, pesan, oleh):
    baris = ["🚨 ALARM DARURAT RUKUNIN", "Jenis: %s" % jenis]
    if pesan:
        baris.append("Pesan: %s" % pesan)
    baris += ["Dinyalakan oleh: %s" % oleh, "Waktu: %s" % datetime.now().strftime("%d-%m-%Y %H:%M")]
    url = _url_panel()
    if url:
        baris.append("Buka panel: %s" % url)
    return "\n".join(baris)


def teks_alarm_stop(jenis, oleh):
    return "✅ Alarm darurat dihentikan\nSituasi '%s' telah dinyatakan selesai oleh %s." % (jenis, oleh)


# ---------------------------------------------------------------- siaran ke semua chat
def siarkan(teks, kecuali=None, audio=None):
    """Kirim `teks` (plus sirene `audio` berupa path MP3, bila diberikan) ke semua chat terdaftar tanpa menunda respons web
    (berjalan di thread terpisah).
    Mengembalikan jumlah chat tujuan. Tidak pernah melempar error: Telegram bermasalah tidak boleh menggagalkan alarm."""
    token = _token()
    if not token or (current_app.config.get("TELEGRAM_MODE") or "polling").lower() == "off":
        return 0
    tujuan = [c for c in chat_ids() if c != str(kecuali)]
    if not tujuan:
        return 0
    if current_app.config.get("TELEGRAM_ASYNC", True):
        threading.Thread(target=_kirim_banyak, args=(token, tujuan, teks, audio), daemon=True).start()
    else:
        _kirim_banyak(token, tujuan, teks, audio)
    return len(tujuan)


def kirim_tes():
    """Kirim pesan uji secara sinkron ke semua chat terdaftar. Dipakai tombol 'Kirim pesan tes' di panel."""
    tujuan = chat_ids()
    berhasil, gagal = _kirim_banyak(_token(), tujuan, "✅ Tes koneksi RUKUNIN: bot Telegram tersambung ke sistem alarm darurat.")
    return {"tujuan": len(tujuan), "berhasil": berhasil, "gagal": [{"chat": c, "sebab": s} for c, s in gagal]}


# ---------------------------------------------------------------- memproses pesan masuk
def _catat(aksi, detail):
    """Catat ke Log Aktivitas. core.log() tidak bisa dipakai di sini karena butuh sesi/permintaan web."""
    core.ex("INSERT INTO activity_log(user_id,aksi,detail,ip) VALUES(?,?,?,?)", (None, aksi, (detail or "")[:300], "telegram"))


def _path_sirene():
    """Sirene yang sedang dipakai panel web (unggahan Ketua RT atau bawaan); None bila tidak bisa ditentukan."""
    try:
        from .views.darurat import _siren_path      # impor di sini untuk menghindari impor melingkar
        return _siren_path()
    except Exception:
        return None


def _nyalakan_alarm(chat_id, pengirim, teks):
    """Buat alarm baru dari Telegram. Mengembalikan id alarm, atau None bila sudah ada alarm yang aktif."""
    if core.scalar("SELECT 1 FROM alarm_darurat WHERE status='aktif' LIMIT 1"):
        return None
    jenis = "Darurat via Telegram"
    pesan = ("Dari %s: %s" % (pengirim, teks))[:500]
    aid = core.ex("INSERT INTO alarm_darurat(jenis, pesan, status, diaktifkan_oleh) VALUES(?, ?, 'aktif', NULL)", (jenis, pesan))
    _catat("darurat_aktifkan", "#%d via Telegram dari %s (chat %s)" % (aid, pengirim, chat_id))
    semua = [r["id"] for r in core.q("SELECT id FROM users WHERE aktif=1")]
    core.notify(semua, "🚨 ALARM DARURAT: %s" % jenis, pesan, "/darurat")
    siarkan(teks_alarm_aktif(jenis, pesan, "Bot Telegram (%s)" % pengirim), kecuali=chat_id, audio=_path_sirene())
    ntfy_push.siarkan("🚨 ALARM DARURAT: %s" % jenis, "%s\nDinyalakan oleh: Bot Telegram (%s)" % (pesan, pengirim))
    return aid


def proses_update(update):
    """Proses satu update Telegram. Harus dipanggil di dalam app context (atau request)."""
    pesan = update.get("message")
    if not pesan:
        return
    token = _token()
    chat = pesan.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    teks = (pesan.get("text") or "").strip()
    dari = pesan.get("from") or {}
    pengirim = "@" + dari["username"] if dari.get("username") else (dari.get("first_name") or "Tanpa Username")
    if not chat_id or not teks:
        return

    perintah = teks.split()[0].split("@")[0].lower() if teks.startswith("/") else ""
    terdaftar = chat_id in chat_ids()

    # /start dan /id selalu dijawab: dipakai untuk mengetahui Chat ID yang harus didaftarkan
    if perintah in ("/start", "/id"):
        if terdaftar:
            _kirim(token, chat_id, "Halo! Chat ini sudah terhubung ke RUKUNIN.\n"
                                   "Kirim kata \"darurat\" atau \"bahaya\" untuk membunyikan alarm. /status untuk cek alarm.")
        else:
            _kirim(token, chat_id, "Chat ID Anda: %s\n\nChat ini belum terdaftar. Minta admin RUKUNIN memasukkan ID di atas "
                                   "pada Pengaturan Sistem (kolom Telegram) agar bisa menerima dan mengirim alarm." % chat_id)
        return

    # Chat tidak terdaftar diabaikan, supaya orang asing tidak bisa membunyikan sirene warga
    if not terdaftar:
        if chat.get("type") == "private":
            _kirim(token, chat_id, "Chat ini belum terdaftar di RUKUNIN. Kirim /id untuk melihat Chat ID Anda.")
        return

    if perintah == "/status":
        a = core.q("SELECT * FROM alarm_darurat WHERE status='aktif' ORDER BY id DESC LIMIT 1", one=True)
        if a is not None:
            _kirim(token, chat_id, "🚨 Alarm AKTIF: %s\n%s\nSejak %s" % (a["jenis"], a["pesan"] or "-", a["diaktifkan_pada"]))
        else:
            _kirim(token, chat_id, "✅ Status: Aman. Tidak ada alarm yang aktif.")
        return

    _catat("telegram_pesan", "%s (chat %s): %s" % (pengirim, chat_id, teks))

    if any(k in teks.lower() for k in KATA_DARURAT):
        if time.time() - (pesan.get("date") or time.time()) > MAKS_UMUR_DETIK:
            _catat("telegram_basi", "Pesan darurat lama diabaikan (dikirim saat server mati?): %s" % teks)
            _kirim(token, chat_id, "⚠️ Pesan darurat Anda tiba terlambat (server RUKUNIN sempat mati), alarm tidak dinyalakan otomatis. "
                                   "Kirim ulang jika masih darurat.")
            return
        if _nyalakan_alarm(chat_id, pengirim, teks):
            _kirim(token, chat_id, "🚨 SIRENE AKTIF! Darurat tercatat di sistem RUKUNIN.")
        else:
            _kirim(token, chat_id, "⚠️ Alarm sudah aktif. Ketua RT dapat mematikannya lewat website RUKUNIN.")
    else:
        _kirim(token, chat_id, "Pesan diterima: %s" % teks)


# ---------------------------------------------------------------- mode webhook
@bp.post("/telegram/webhook")
def webhook():
    """Dipanggil server Telegram (tanpa sesi login, jadi dikecualikan dari CSRF di core.py).
    Keasliannya diperiksa lewat header rahasia yang didaftarkan saat setWebhook."""
    token = _token()
    if not token:
        abort(404)
    terkirim = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") or "").encode("utf-8")
    if not hmac.compare_digest(terkirim, _webhook_secret(token).encode("utf-8")):
        abort(403)
    try:
        proses_update(request.get_json(silent=True) or {})
    except Exception:
        current_app.logger.exception("Gagal memproses update Telegram")
    return jsonify(ok=True)          # selalu 200, agar Telegram tidak mengulang kiriman yang sama


# ---------------------------------------------------------------- mode polling
def _polling(app):
    token = app.config["TELEGRAM_BOT_TOKEN"]
    offset, gagal, peringatan = None, 0, False
    # getUpdates ditolak (409) bila Telegram masih punya webhook lama (mis. dari ngrok), jadi hapus dulu
    _api(token, "deleteWebhook", {"drop_pending_updates": False})
    while not _STOP.is_set():
        payload = {"timeout": 25, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        r = _api(token, "getUpdates", payload, timeout=40)
        if not r.get("ok"):
            gagal += 1
            if r.get("error_code") == 401:
                print("[Telegram] Token bot ditolak (401). Periksa TELEGRAM_BOT_TOKEN / instance/telegram_token.txt. Bot berhenti.", flush=True)
                return
            if r.get("error_code") == 409 and not peringatan:
                print("[Telegram] Konflik (409): ada program lain yang juga membaca bot ini (mis. app.py bot lama masih jalan). "
                      "Tutup yang lama.", flush=True)
                peringatan = True
            _STOP.wait(min(60, 3 * gagal))
            continue
        gagal, peringatan = 0, False
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            try:
                with app.app_context():
                    proses_update(u)
            except Exception:
                app.logger.exception("Gagal memproses update Telegram")


def _mulai(app, mode):
    """Dijalankan di thread: ambil nama bot, lalu pasang webhook atau mulai polling."""
    global _BOT_USERNAME
    token = app.config["TELEGRAM_BOT_TOKEN"]
    me = _api(token, "getMe")
    if me.get("ok"):
        _BOT_USERNAME = "@" + (me["result"].get("username") or "")
        print("[Telegram] Bot terhubung: %s (mode %s)" % (_BOT_USERNAME, mode), flush=True)
    elif me.get("error_code") == 401:
        print("[Telegram] Token bot ditolak (401). Periksa TELEGRAM_BOT_TOKEN / instance/telegram_token.txt.", flush=True)
        return
    else:
        print("[Telegram] Belum bisa menghubungi Telegram (%s). Akan dicoba terus." % me.get("description"), flush=True)

    if mode == "webhook":
        base = (app.config.get("TELEGRAM_WEBHOOK_URL") or "").rstrip("/")
        if not base.startswith("https://"):
            print("[Telegram] Mode webhook butuh TELEGRAM_WEBHOOK_URL berawalan https:// (alamat publik, mis. dari ngrok).", flush=True)
            return
        r = _api(token, "setWebhook", {"url": base + "/telegram/webhook", "secret_token": _webhook_secret(token),
                                       "allowed_updates": ["message"]})
        print("[Telegram] setWebhook: %s" % ("berhasil" if r.get("ok") else r.get("description")), flush=True)
    else:
        _polling(app)


def init_app(app):
    """Daftarkan route webhook dan jalankan bot di latar belakang (dipanggil dari create_app)."""
    global _THREAD
    app.register_blueprint(bp)
    if not app.testing and not (app.config.get("TELEGRAM_BOT_TOKEN") or "").strip():
        app.config["TELEGRAM_BOT_TOKEN"] = TOKEN_BAWAAN.strip()      # semua bagian lain membaca token dari app.config
    mode = (app.config.get("TELEGRAM_MODE") or "polling").lower()
    if app.testing or mode == "off" or not (app.config.get("TELEGRAM_BOT_TOKEN") or "").strip():
        if not app.testing and mode != "off":
            print("[Telegram] Token belum diisi -> bot nonaktif. Isi TOKEN_BAWAAN di telegram_bot.py, instance/telegram_token.txt, atau TELEGRAM_BOT_TOKEN.", flush=True)
        return
    # Mode debug Flask menjalankan kode ini dua kali (proses induk + proses anak): jalankan bot hanya di proses anak
    if os.environ.get("FLASK_DEBUG") == "1" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    if _THREAD and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_mulai, args=(app, mode), name="telegram-bot", daemon=True)
    _THREAD.start()
