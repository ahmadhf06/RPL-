"""Alarm ke HP lewat ntfy (https://ntfy.sh): notifikasi prioritas tertinggi yang BERBUNYI SENDIRI di HP.

Kenapa ntfy, bukan hanya Telegram: bot Telegram tidak bisa membuat HP memutar audio otomatis; yang berbunyi hanya
nada notifikasi biasa. Aplikasi ntfy (Android/iOS) menerima pesan berprioritas 5 sebagai notifikasi "max": getaran panjang,
pop-over, dan di Android suaranya bisa diatur per-prioritas (nada sendiri, menembus Jangan Ganggu, bahkan diulang terus).

Cara kerja: server RUKUNIN mengirim satu permintaan HTTPS ke ntfy.sh untuk sebuah "topik". Setiap HP yang berlangganan
topik itu di aplikasi ntfy langsung menerimanya. Topik berfungsi seperti kata sandi: siapa pun yang tahu namanya bisa
membaca dan mengirim ke topik itu, karena itu namanya dibuat ACAK (disimpan di instance/ntfy_topic.txt) dan hanya
ditampilkan kepada Ketua RT / admin di panel Alarm Darurat. Isi pesan lewat server ntfy.sh (pihak ketiga); matikan dengan NTFY_MODE=off.
"""
import json
import os
import re
import secrets
import threading
import urllib.error
import urllib.request

from flask import current_app

_LOCK = threading.Lock()
_TOPIK_SEMENTARA = ""                     # dipakai hanya bila berkas topik tidak bisa ditulis


# ---------------------------------------------------------------- HTTP (satu-satunya titik keluar ke internet)
def _post(server, payload, timeout=10):
    """Kirim JSON ke server ntfy (publish as JSON: POST ke alamat utama). Mengembalikan (status_http, isi); tidak melempar error."""
    req = urllib.request.Request(server.rstrip("/") + "/", data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return e.code, str(e)
    except Exception as e:                      # tidak ada internet, timeout, dsb.
        return 0, str(e)


# ---------------------------------------------------------------- konfigurasi
def _bersih(t):
    return re.sub(r"[^-_A-Za-z0-9]", "", t or "")[:64]          # ntfy: huruf, angka, _ dan - (maks. 64)


def aktif():
    if (current_app.config.get("NTFY_MODE") or "on").lower() == "off":
        return False
    return not (current_app.testing and not current_app.config.get("NTFY_UJI"))      # uji otomatis tidak menyentuh internet


def topik():
    """Nama topik: NTFY_TOPIC, atau berkas instance/ntfy_topic.txt (dibuat acak saat pertama kali dibutuhkan)."""
    global _TOPIK_SEMENTARA
    t = _bersih(current_app.config.get("NTFY_TOPIC"))
    if t:
        return t
    path = current_app.config.get("NTFY_TOPIC_FILE")
    with _LOCK:
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    t = _bersih(f.read())
            except OSError:
                t = ""
            if t:
                return t
        t = _TOPIK_SEMENTARA or "rukunin-" + secrets.token_urlsafe(18)
        try:
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(t)
                _TOPIK_SEMENTARA = ""
            else:
                _TOPIK_SEMENTARA = t
        except OSError:
            _TOPIK_SEMENTARA = t
        return t


def _server():
    return (current_app.config.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")


def status():
    """Ringkasan untuk panel Alarm Darurat (topik hanya dibuat bila fitur aktif)."""
    on = aktif()
    t = topik() if on else ""
    host = re.sub(r"^https?://", "", _server())
    return {"aktif": on, "topik": t, "server": host, "tautan": "ntfy://%s/%s" % (host, t) if t else ""}


def _url_panel():
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    return base + "/darurat" if base else ""


# ---------------------------------------------------------------- kirim
def _kirim(server, payload):
    status_http, isi = _post(server, payload)
    if status_http != 200:
        print("[ntfy] Gagal kirim notifikasi (HTTP %s): %s" % (status_http, isi[:120]), flush=True)
    return status_http == 200


def _payload(judul, pesan, prioritas, tags):
    p = {"topic": topik(), "title": judul[:250], "message": pesan[:1500], "priority": prioritas, "tags": list(tags)}
    url = _url_panel()
    if url:
        p["click"] = url                       # ketuk notifikasi -> membuka panel alarm
    return p


def siarkan(judul, pesan, prioritas=5, tags=("rotating_light",)):
    """Kirim notifikasi ke semua HP yang berlangganan topik, di thread terpisah. Tidak pernah melempar error:
    ntfy bermasalah tidak boleh menggagalkan alarm. Prioritas 5 = berbunyi, 3 = biasa. Mengembalikan 1 bila dikirim."""
    if not aktif():
        return 0
    payload, server = _payload(judul, pesan, prioritas, tags), _server()
    if current_app.config.get("NTFY_ASYNC", True):
        threading.Thread(target=_kirim, args=(server, payload), daemon=True).start()
    else:
        _kirim(server, payload)
    return 1


def kirim_tes():
    """Notifikasi uji berprioritas 5 (terdengar seperti alarm sungguhan) secara sinkron. Dipakai tombol di panel."""
    payload = _payload("Tes RUKUNIN", "Jika HP berbunyi dan notifikasi ini muncul, alarm otomatis ke HP sudah siap.", 5, ("bell",))
    status_http, isi = _post(_server(), payload)
    return {"ok": status_http == 200, "status": status_http, "keterangan": "" if status_http == 200 else isi[:200]}
