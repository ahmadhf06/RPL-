"""Uji integrasi bot Telegram <-> alarm darurat.  Jalankan:  python -m pytest -q tests/test_telegram.py
Semua panggilan ke Telegram diganti tiruan (tidak butuh internet / token asli)."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartrt import core, create_app, telegram_bot  # noqa: E402

PW = {"admin": "Admin#2026", "ketua": "Ketua#2026", "warga": "Warga#2026"}
TOKEN = "123456:TOKEN-PALSU"
SECRET = telegram_bot._webhook_secret(TOKEN)
HDR = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
CHAT_A, CHAT_GRUP, CHAT_ASING = "111", "-100222", "999"


@pytest.fixture()
def app(tmp_path, monkeypatch):
    core._FAILS.clear()
    telegram_bot._AUDIO_CACHE.clear()
    terkirim = []                                    # (chat_id, teks) semua pesan keluar ke Telegram (teks atau keterangan audio)
    rincian = []                                     # (chat_id, metode, ada_unggahan_berkas)

    def api_palsu(token, metode, payload=None, timeout=15, berkas=None):
        assert token == TOKEN
        if metode == "sendMessage":
            terkirim.append((str(payload["chat_id"]), payload["text"]))
            rincian.append((str(payload["chat_id"]), metode, False))
        elif metode == "sendAudio":
            terkirim.append((str(payload["chat_id"]), payload["caption"]))
            rincian.append((str(payload["chat_id"]), metode, bool(berkas)))
            return {"ok": True, "result": {"audio": {"file_id": "FID-SIRENE"}}}
        return {"ok": True, "result": {}}

    monkeypatch.setattr(telegram_bot, "_api", api_palsu)
    a = create_app({"DATABASE": str(tmp_path / "t.db"), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True,
                    "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_IDS": "%s, %s" % (CHAT_A, CHAT_GRUP),
                    "TELEGRAM_ASYNC": False})
    a.terkirim = terkirim
    a.rincian = rincian
    return a


def tok(c):
    with c.session_transaction() as s:
        return s["csrf"]


def login(app, user):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"username": user, "password": PW[user], "csrf_token": tok(c)})
    assert r.status_code == 302, user
    return c


def kirim_tg(app, chat_id, teks, username="budi", tipe="private", umur=0, header=HDR):
    """Meniru Telegram yang memanggil webhook."""
    update = {"update_id": 1, "message": {"date": int(time.time()) - umur, "text": teks,
                                          "chat": {"id": int(chat_id), "type": tipe},
                                          "from": {"id": 5, "username": username, "first_name": "Budi"}}}
    return app.test_client().post("/telegram/webhook", json=update, headers=header)


def alarm_rows(app):
    with app.app_context():
        return [dict(r) for r in core.q("SELECT * FROM alarm_darurat ORDER BY id")]


def test_webhook_wajib_header_rahasia_dan_bebas_csrf(app):
    c = app.test_client()
    assert c.post("/telegram/webhook", json={}).status_code == 403                                   # tanpa header
    assert c.post("/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "salah"}).status_code == 403
    assert kirim_tg(app, CHAT_A, "halo").status_code == 200       # tanpa token CSRF, tetapi header benar -> lolos
    assert c.post("/login", data={"username": "admin", "password": "x"}).status_code == 400          # CSRF tetap aktif di route lain


def test_pesan_darurat_dari_telegram_menyalakan_alarm_di_web(app):
    r = kirim_tg(app, CHAT_A, "Ada bahaya banjir di gang 3")
    assert r.status_code == 200
    rows = alarm_rows(app)
    assert len(rows) == 1 and rows[0]["status"] == "aktif" and rows[0]["diaktifkan_oleh"] is None
    assert "@budi" in rows[0]["pesan"] and "banjir" in rows[0]["pesan"]

    # pengirim dibalas, chat lain (grup) mendapat siaran, pengirim tidak dapat dobel
    keluar = app.terkirim
    assert [t for c, t in keluar if c == CHAT_A and "SIRENE AKTIF" in t]
    assert [t for c, t in keluar if c == CHAT_GRUP and "ALARM DARURAT RUKUNIN" in t]
    assert not [t for c, t in keluar if c == CHAT_A and "ALARM DARURAT RUKUNIN" in t]

    # halaman web melihat alarm lewat endpoint yang di-poll alarm.js, dan sirene tersedia (bawaan dari bot)
    w = login(app, "warga")
    st = w.get("/api/darurat/status").get_json()
    assert st["aktif"] is True and st["jenis"] == "Darurat via Telegram"
    s = w.get("/api/darurat/sirene")
    assert s.status_code == 200 and s.mimetype == "audio/mpeg" and len(s.data) > 10000
    assert b"Bot Telegram" in login(app, "ketua").get("/darurat").data

    # semua akun aktif mendapat notifikasi di web
    with app.app_context():
        assert core.scalar("SELECT COUNT(*) FROM notifikasi WHERE judul LIKE '%ALARM DARURAT%'") >= 5


def test_alarm_ganda_dan_chat_asing_dan_pesan_basi(app):
    kirim_tg(app, CHAT_A, "darurat")
    kirim_tg(app, CHAT_GRUP, "darurat lagi", tipe="group")
    assert len(alarm_rows(app)) == 1                                              # tidak membuat alarm kedua
    assert [t for c, t in app.terkirim if c == CHAT_GRUP and "sudah aktif" in t]

    app.terkirim.clear()
    kirim_tg(app, CHAT_ASING, "darurat")                                           # chat yang belum terdaftar
    assert len(alarm_rows(app)) == 1
    assert app.terkirim == [(CHAT_ASING, "Chat ini belum terdaftar di RUKUNIN. Kirim /id untuk melihat Chat ID Anda.")]

    app.terkirim.clear()
    kirim_tg(app, CHAT_ASING, "darurat", tipe="supergroup")                        # grup asing: diam saja
    assert app.terkirim == [] and len(alarm_rows(app)) == 1


def test_pesan_darurat_lama_tidak_menyalakan_alarm(app):
    kirim_tg(app, CHAT_A, "darurat", umur=3600)                                     # dikirim sejam lalu saat server mati
    assert alarm_rows(app) == []
    assert [t for c, t in app.terkirim if "terlambat" in t]


def test_perintah_id_start_status_dan_pesan_biasa(app):
    kirim_tg(app, CHAT_ASING, "/id")
    assert "Chat ID Anda: 999" in app.terkirim[-1][1]
    kirim_tg(app, CHAT_A, "/start@RukuninBot")
    assert "sudah terhubung" in app.terkirim[-1][1]
    kirim_tg(app, CHAT_A, "/status")
    assert "Aman" in app.terkirim[-1][1]
    kirim_tg(app, CHAT_A, "selamat pagi pak RT")
    assert app.terkirim[-1] == (CHAT_A, "Pesan diterima: selamat pagi pak RT")
    assert alarm_rows(app) == []
    kirim_tg(app, CHAT_A, "darurat")
    kirim_tg(app, CHAT_A, "/status")
    assert "Alarm AKTIF" in app.terkirim[-1][1]


def test_alarm_dari_web_dikirim_ke_telegram_dan_stop(app):
    w = login(app, "warga")
    r = w.post("/api/darurat/aktifkan", json={"jenis": "Kebakaran", "pesan": "Rumah no 5"}, headers={"X-CSRF-Token": tok(w)})
    assert r.get_json()["ok"] is True
    kena = {c for c, t in app.terkirim if "Kebakaran" in t and "Rumah no 5" in t}
    assert kena == {CHAT_A, CHAT_GRUP}

    app.terkirim.clear()
    k = login(app, "ketua")
    assert k.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(k)}).get_json()["ok"] is True
    assert {c for c, t in app.terkirim if "dihentikan" in t} == {CHAT_A, CHAT_GRUP}


def test_telegram_bermasalah_tidak_menggagalkan_alarm_web(app, monkeypatch):
    monkeypatch.setattr(telegram_bot, "_api", lambda *a, **k: {"ok": False, "error_code": 0, "description": "tidak ada internet"})
    w = login(app, "warga")
    r = w.post("/api/darurat/aktifkan", json={"jenis": "Banjir"}, headers={"X-CSRF-Token": tok(w)})
    assert r.get_json()["ok"] is True and len(alarm_rows(app)) == 1


def test_chat_id_dari_pengaturan_admin_dan_tes_telegram(app):
    a = login(app, "admin")
    data = {"nama_rt": "RT 01", "iuran_bulanan": "50000", "telegram_chat_ids": "777, -100888", "csrf_token": tok(a)}
    assert a.post("/admin/pengaturan", data=data).status_code == 302
    with app.app_context():
        assert telegram_bot.chat_ids() == ["111", "-100222", "777", "-100888"]

    app.terkirim.clear()
    r = a.post("/api/darurat/telegram-tes", json={}, headers={"X-CSRF-Token": tok(a)})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and j["berhasil"] == 4 and len(app.terkirim) == 4
    assert alarm_rows(app) == []                                                    # tes tidak menyalakan sirene

    w = login(app, "warga")
    assert w.post("/api/darurat/telegram-tes", json={}, headers={"X-CSRF-Token": tok(w)}).status_code == 403


def test_tes_telegram_tanpa_token_atau_chat(tmp_path):
    a = create_app({"DATABASE": str(tmp_path / "x.db"), "UPLOAD_FOLDER": str(tmp_path / "u"), "TESTING": True,
                    "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_IDS": ""})
    k = login(a, "ketua")
    r = k.post("/api/darurat/telegram-tes", json={}, headers={"X-CSRF-Token": tok(k)})
    assert r.status_code == 400 and "Token" in r.get_json()["pesan"]
    assert a.test_client().post("/telegram/webhook", json={}).status_code == 404       # tanpa token webhook tidak aktif
    page = k.get("/darurat").data
    assert b"Token belum diisi" in page


# ---------------------------------------------------------------- sirene sebagai pesan audio di HP
def test_alarm_web_dikirim_sebagai_satu_pesan_audio_sirene(app):
    w = login(app, "warga")
    w.post("/api/darurat/aktifkan", json={"jenis": "Kebakaran", "pesan": "Rumah no 5"}, headers={"X-CSRF-Token": tok(w)})
    # satu pesan per chat (satu notifikasi): audio sirene dengan keterangan alarm sebagai caption
    assert sorted(app.rincian) == sorted([(CHAT_A, "sendAudio", True), (CHAT_GRUP, "sendAudio", False)])   # unggah sekali, sisanya file_id
    assert all("Kebakaran" in t and "Rumah no 5" in t for c, t in app.terkirim) and len(app.terkirim) == 2

    k = login(app, "ketua")                                                        # berhenti: hanya teks, tanpa audio
    app.rincian.clear()
    k.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(k)})
    assert {m for c, m, u in app.rincian} == {"sendMessage"}


def test_alarm_dari_telegram_membawa_sirene_ke_chat_lain(app):
    kirim_tg(app, CHAT_A, "darurat")
    assert (CHAT_GRUP, "sendAudio", True) in app.rincian
    assert (CHAT_A, "sendMessage", False) in app.rincian and not [r for r in app.rincian if r[0] == CHAT_A and r[1] == "sendAudio"]


def test_sirene_ditolak_telegram_jatuh_ke_teks_biasa(app, monkeypatch):
    asli = telegram_bot._api

    def tolak_audio(token, metode, payload=None, timeout=15, berkas=None):
        if metode == "sendAudio":
            return {"ok": False, "error_code": 400, "description": "wrong file type"}
        return asli(token, metode, payload, timeout, berkas)

    monkeypatch.setattr(telegram_bot, "_api", tolak_audio)
    w = login(app, "warga")
    w.post("/api/darurat/aktifkan", json={"jenis": "Banjir"}, headers={"X-CSRF-Token": tok(w)})
    assert {c for c, t in app.terkirim if "Banjir" in t} == {CHAT_A, CHAT_GRUP}            # tetap sampai sebagai teks


def test_sirene_bukan_mp3_dikirim_sebagai_teks(app):
    k = login(app, "ketua")
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 64
    import io
    r = k.post("/api/darurat/upload-sirene", data={"sirene": (io.BytesIO(wav), "s.wav")}, headers={"X-CSRF-Token": tok(k)})
    assert r.get_json()["ok"] is True
    k.post("/api/darurat/aktifkan", json={"jenis": "Gempa"}, headers={"X-CSRF-Token": tok(k)})
    assert {m for c, m, u in app.rincian} == {"sendMessage"} and len(app.terkirim) == 2


def test_badan_multipart_dan_chat_id_bawaan(app, monkeypatch):
    body, jenis = telegram_bot._multipart({"chat_id": "111", "caption": "Halo 🚨"}, {"audio": ("s.mp3", b"ID3\x00\xff", "audio/mpeg")})
    batas = jenis.split("boundary=")[1]
    assert body.count(("--" + batas).encode()) == 4 and body.endswith(("--" + batas + "--\r\n").encode())
    assert b'name="chat_id"\r\n\r\n111' in body and "Halo 🚨".encode() in body
    assert b'filename="s.mp3"' in body and b"ID3\x00\xff" in body

    monkeypatch.setattr(telegram_bot, "CHAT_ID_BAWAAN", "555, -100666")
    with app.app_context():
        assert telegram_bot.chat_ids() == ["555", "-100666", "111", "-100222"]
