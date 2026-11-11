"""Dynamic Voice Emergency Alert System – backend endpoint.

Endpoints:
  GET  /darurat                   – halaman panel alarm
  GET  /api/darurat/status        – status alarm aktif (JSON, publik untuk sesama pengguna login)
  POST /api/darurat/upload        – unggah rekaman warga (warga / ketua)
  POST /api/darurat/aktifkan      – aktifkan alarm (ketua)
  POST /api/darurat/stop          – hentikan alarm (ketua)
  GET  /api/darurat/sirene        – unduh / putar file sirene template
  GET  /api/darurat/rekaman       – unduh / putar rekaman aktif
  POST /api/darurat/telegram-tes  – kirim pesan uji ke semua chat Telegram terdaftar (ketua / admin)
  POST /api/darurat/ntfy-tes      – kirim notifikasi uji berbunyi ke HP yang berlangganan ntfy (ketua / admin)

Bot Telegram (smartrt/telegram_bot.py) memakai tabel alarm_darurat yang sama: alarm yang dinyalakan / dimatikan di sini
dikirim ke Telegram, dan pesan "darurat" / "bahaya" dari Telegram menyalakan alarm di sini.
"""
import os
import re
import uuid

from flask import (Blueprint, abort, current_app, jsonify, redirect,
                   render_template, request, send_file, url_for)

from .. import ntfy_push, telegram_bot
from ..core import (ROLES, current_user, ex, log, login_required, notify, q,
                    roles_required, scalar, users_by_role)

bp = Blueprint("darurat", __name__)

# Folder khusus darurat di dalam instance/uploads
_SIREN_BASE = "sirene_template"                    # nama dasar file sirene permanen
_SIREN_EXTS = ("mp3", "webm", "ogg", "wav")        # ekstensi yang diizinkan
_SIREN_MIME = {"mp3": "audio/mpeg", "webm": "audio/webm",
               "ogg": "audio/ogg", "wav": "audio/wav"}


def _darurat_dir() -> str:
    d = os.path.join(current_app.config["UPLOAD_FOLDER"], "darurat")
    os.makedirs(d, exist_ok=True)
    return d


def _siren_path() -> str:
    """Path sirene yang dipakai: unggahan Ketua RT/admin bila ada, jika tidak sirene bawaan (static/audio/alarm.mp3,
    berasal dari bot Telegram), jika itu pun hilang path mp3 kosong."""
    d = _darurat_dir()
    for ext in _SIREN_EXTS:
        p = os.path.join(d, f"{_SIREN_BASE}.{ext}")
        if os.path.isfile(p):
            return p
    bawaan = os.path.join(current_app.root_path, "static", "audio", "alarm.mp3")
    if os.path.isfile(bawaan):
        return bawaan
    return os.path.join(d, f"{_SIREN_BASE}.mp3")


def _siren_ext(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower()


def _is_mp3(head: bytes) -> bool:
    """MP3 diawali tag ID3 atau frame sync MPEG (11 bit pertama = 1)."""
    if head[:3] == b"ID3":
        return True
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


def _rekaman_path(filename: str) -> str:
    """Kembalikan path lengkap rekaman aktif; filename sudah divalidasi."""
    return os.path.join(_darurat_dir(), filename)


def _safe_audio_name(name: str) -> bool:
    """Izinkan hanya nama file berformat UUID hex + ekstensi audio."""
    return bool(re.fullmatch(r"[0-9a-f]{32}\.(webm|ogg|wav|mp4|m4a)", name))


def _alarm_aktif():
    """Kembalikan baris alarm yang sedang aktif, atau None."""
    return q("SELECT * FROM alarm_darurat WHERE status='aktif' ORDER BY id DESC LIMIT 1",
             one=True)


# ---------------------------------------------------------------- halaman utama
@bp.route("/darurat")
@login_required
def panel():
    u = current_user()
    alarm = _alarm_aktif()
    logs = q(
        "SELECT a.*, u.nama AS aktivator, s.nama AS penghenti "
        "FROM alarm_darurat a "
        "LEFT JOIN users u ON u.id = a.diaktifkan_oleh "
        "LEFT JOIN users s ON s.id = a.dihentikan_oleh "
        "ORDER BY a.id DESC LIMIT 20"
    )
    siren_ada = os.path.isfile(_siren_path())
    return render_template("darurat/index.html", alarm=alarm, logs=logs,
                           siren_ada=siren_ada, u=u, tg=telegram_bot.status(), ntfy=ntfy_push.status())


# ---------------------------------------------------------------- API status (JSON)
@bp.get("/api/darurat/status")
@login_required
def api_status():
    alarm = _alarm_aktif()
    if not alarm:
        return jsonify(aktif=False)
    return jsonify(
        aktif=True,
        id=alarm["id"],
        jenis=alarm["jenis"],
        pesan=alarm["pesan"],
        rekaman=alarm["rekaman_file"],
        diaktifkan_pada=alarm["diaktifkan_pada"],
    )


# ---------------------------------------------------------------- upload rekaman warga
@bp.post("/api/darurat/upload")
@roles_required("warga", "ketua", "sekretaris", "bendahara", "humas")
def upload_rekaman():
    """Terima blob audio dari MediaRecorder browser, simpan sementara."""
    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify(ok=False, pesan="Berkas audio tidak ditemukan."), 400

    # Baca 12 byte pertama untuk deteksi format
    head = f.stream.read(12)
    f.stream.seek(0)

    # Deteksi format: WebM, OGG, WAV, MP4/M4A
    if head[:4] == b"\x1aEw\xa3" or head[4:8] == b"webm":   # WebM
        ext = "webm"
    elif head[:4] == b"OggS":                                  # OGG
        ext = "ogg"
    elif head[:4] == b"RIFF" and head[8:12] == b"WAVE":       # WAV
        ext = "wav"
    elif head[4:8] == b"ftyp":                                 # MP4/M4A
        ext = "m4a"
    else:
        # Fallback: terima apa saja yang dikirim browser (beberapa browser
        # mengirim WebM tanpa header 'webm' yang bisa dideteksi sederhana)
        ext = "webm"

    name = f"{uuid.uuid4().hex}.{ext}"
    save_path = _rekaman_path(name)
    f.save(save_path)

    u = current_user()
    log("darurat_upload_rekaman", f"{name} oleh {u['nama']}")
    return jsonify(ok=True, filename=name)


# ---------------------------------------------------------------- aktifkan alarm
@bp.post("/api/darurat/aktifkan")
@roles_required("warga", "ketua", "sekretaris", "bendahara", "humas", "admin")
def aktifkan():
    """Aktifkan alarm: simpan baris baru di tabel, notifikasi semua user.
    Dapat dinyalakan oleh semua aktor tanpa popup konfirmasi."""
    # Cek alarm sebelumnya masih aktif
    if _alarm_aktif():
        return jsonify(ok=False, pesan="Alarm sedang aktif. Hentikan dulu sebelum mengaktifkan yang baru."), 409

    data = request.get_json(silent=True) or {}
    jenis = (data.get("jenis") or "").strip()[:60] or "Keadaan Darurat Lingkungan"
    pesan = (data.get("pesan") or "").strip()[:500] or "Alarm darurat dinyalakan segera! Seluruh warga dimohon waspada."
    rekaman = (data.get("rekaman") or "").strip()

    if rekaman and not _safe_audio_name(rekaman):
        return jsonify(ok=False, pesan="Nama file rekaman tidak valid."), 400
    if rekaman and not os.path.isfile(_rekaman_path(rekaman)):
        return jsonify(ok=False, pesan="File rekaman tidak ditemukan di server."), 400

    u = current_user()
    aid = ex(
        "INSERT INTO alarm_darurat(jenis, pesan, rekaman_file, status, diaktifkan_oleh) "
        "VALUES(?, ?, ?, 'aktif', ?)",
        (jenis, pesan, rekaman or None, u["id"])
    )

    log("darurat_aktifkan", f"#{aid} jenis={jenis} oleh {u['nama']} ({u['role']})")

    # Notifikasi ke semua pengguna aktif
    semua = [r["id"] for r in q("SELECT id FROM users WHERE aktif=1 AND id<>?", (u["id"],))]
    notify(semua, f"🚨 ALARM DARURAT: {jenis}", pesan or "Warga dimohon waspada.",
           url_for("darurat.panel"))

    # Kirim juga ke Telegram supaya HP warga berbunyi walau tidak sedang membuka web
    oleh = f"{u['nama']} ({ROLES.get(u['role'], u['role'])})"
    telegram_bot.siarkan(telegram_bot.teks_alarm_aktif(jenis, pesan + (" [ada pesan suara di panel web]" if rekaman else ""), oleh),
                         audio=_siren_path())
    # Notifikasi prioritas tertinggi ke HP lewat ntfy: berbunyi sendiri tanpa membuka chat/web
    ntfy_push.siarkan(f"🚨 ALARM DARURAT: {jenis}", f"{pesan}\nDinyalakan oleh: {oleh}")

    return jsonify(ok=True, id=aid)


# ---------------------------------------------------------------- stop alarm
@bp.post("/api/darurat/stop")
@roles_required("ketua")
def stop_alarm():
    """Hentikan alarm aktif, hapus rekaman warga dari storage aktif."""
    alarm = _alarm_aktif()
    if not alarm:
        return jsonify(ok=False, pesan="Tidak ada alarm yang sedang aktif."), 404

    u = current_user()
    ex(
        "UPDATE alarm_darurat SET status='selesai', dihentikan_oleh=?, "
        "dihentikan_pada=datetime('now','localtime') WHERE id=?",
        (u["id"], alarm["id"])
    )
    log("darurat_stop", f"#{alarm['id']}")

    # Hapus rekaman warga dari penyimpanan aktif (sirene tidak dihapus)
    rekaman = alarm["rekaman_file"]
    if rekaman:
        try:
            fpath = _rekaman_path(rekaman)
            if os.path.isfile(fpath):
                os.remove(fpath)
        except OSError:
            pass  # gagal hapus bukan error fatal

    # Notifikasi: alarm selesai
    semua = [r["id"] for r in q("SELECT id FROM users WHERE aktif=1 AND id<>?", (u["id"],))]
    notify(semua, "✅ Alarm darurat dihentikan",
           f"Situasi '{alarm['jenis']}' telah dinyatakan selesai oleh petugas.",
           url_for("darurat.panel"))
    telegram_bot.siarkan(telegram_bot.teks_alarm_stop(alarm["jenis"], f"{u['nama']} ({ROLES.get(u['role'], u['role'])})"))
    ntfy_push.siarkan("✅ Alarm darurat dihentikan", f"Situasi '{alarm['jenis']}' telah dinyatakan selesai oleh {u['nama']}.",
                      prioritas=3, tags=("heavy_check_mark",))

    return jsonify(ok=True)


# ---------------------------------------------------------------- streaming audio
@bp.get("/api/darurat/sirene")
@login_required
def serve_sirene():
    """Sajikan file sirene template."""
    path = _siren_path()
    if not os.path.isfile(path):
        abort(404)
    mime = _SIREN_MIME.get(_siren_ext(path), "audio/mpeg")
    return send_file(path, mimetype=mime, conditional=True)


@bp.get("/api/darurat/rekaman")
@login_required
def serve_rekaman():
    """Sajikan rekaman aktif (hanya ketika alarm aktif)."""
    alarm = _alarm_aktif()
    if not alarm or not alarm["rekaman_file"]:
        abort(404)
    name = alarm["rekaman_file"]
    if not _safe_audio_name(name):
        abort(404)
    path = _rekaman_path(name)
    if not os.path.isfile(path):
        abort(404)

    # Tentukan MIME dari ekstensi
    ext = name.rsplit(".", 1)[-1]
    mime_map = {"webm": "audio/webm", "ogg": "audio/ogg",
                "wav": "audio/wav", "m4a": "audio/mp4"}
    mime = mime_map.get(ext, "audio/webm")
    return send_file(path, mimetype=mime, conditional=True)


# ---------------------------------------------------------------- upload sirene (admin/ketua)
@bp.post("/api/darurat/upload-sirene")
@roles_required("ketua", "admin")
def upload_sirene():
    """Ganti file sirene template (format MP3, WebM, OGG, atau WAV)."""
    f = request.files.get("sirene")
    if not f or not f.filename:
        return jsonify(ok=False, pesan="Berkas tidak ditemukan."), 400

    head = f.stream.read(12)
    f.stream.seek(0)

    # Deteksi format dari isi file (bukan dari nama file)
    if _is_mp3(head):
        ext = "mp3"
    elif head[:4] == b"\x1a\x45\xdf\xa3" or b"webm" in head[:12]:
        ext = "webm"
    elif head[:4] == b"OggS":
        ext = "ogg"
    elif head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        ext = "wav"
    else:
        return jsonify(ok=False, pesan="Format harus MP3, WebM, OGG, atau WAV."), 400

    # Simpan dulu ke file sementara; hapus sirene lama hanya jika simpan berhasil
    d = _darurat_dir()
    tmp = os.path.join(d, f"{_SIREN_BASE}.upload.tmp")
    f.save(tmp)
    for old_ext in _SIREN_EXTS:
        old_path = os.path.join(d, f"{_SIREN_BASE}.{old_ext}")
        if os.path.isfile(old_path):
            os.remove(old_path)
    os.replace(tmp, os.path.join(d, f"{_SIREN_BASE}.{ext}"))

    log("darurat_upload_sirene", ext)
    return jsonify(ok=True, format=ext)

# ---------------------------------------------------------------- tes Telegram (admin/ketua)
@bp.post("/api/darurat/telegram-tes")
@roles_required("ketua", "admin")
def telegram_tes():
    """Kirim pesan uji (tanpa menyalakan sirene) ke semua chat Telegram terdaftar."""
    st = telegram_bot.status()
    if not st["token_ada"]:
        return jsonify(ok=False, pesan="Token bot belum diisi. Simpan token di instance/telegram_token.txt lalu jalankan ulang server."), 400
    if st["mode"] == "off":
        return jsonify(ok=False, pesan="Bot Telegram dimatikan (TELEGRAM_MODE=off)."), 400
    if not st["jumlah_chat"]:
        return jsonify(ok=False, pesan="Belum ada Chat ID. Kirim /id ke bot, lalu isi di Pengaturan Sistem (kolom Telegram)."), 400
    hasil = telegram_bot.kirim_tes()
    log("darurat_tes_telegram", f"{hasil['berhasil']}/{hasil['tujuan']} chat")
    if hasil["berhasil"] == 0:
        sebab = hasil["gagal"][0]["sebab"] if hasil["gagal"] else "tidak diketahui"
        return jsonify(ok=False, pesan=f"Pesan tidak terkirim: {sebab}", **hasil), 502
    return jsonify(ok=True, **hasil)


# ---------------------------------------------------------------- tes ntfy (admin/ketua)
@bp.post("/api/darurat/ntfy-tes")
@roles_required("ketua", "admin")
def ntfy_tes():
    """Kirim notifikasi uji berprioritas tertinggi (tanpa menyalakan alarm di web) ke HP yang berlangganan topik ntfy."""
    if not ntfy_push.aktif():
        return jsonify(ok=False, pesan="Notifikasi HP (ntfy) dimatikan (NTFY_MODE=off)."), 400
    hasil = ntfy_push.kirim_tes()
    log("darurat_tes_ntfy", f"HTTP {hasil['status']}")
    if not hasil["ok"]:
        return jsonify(ok=False, pesan="Gagal menghubungi ntfy (HTTP %s): %s" % (hasil["status"] or "tidak ada koneksi", hasil["keterangan"])), 502
    return jsonify(ok=True)
