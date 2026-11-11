"""Uji alarm berbunyi otomatis di HP lewat ntfy.  Jalankan:  python -m pytest -q tests/test_ntfy.py
Tidak butuh internet: pengiriman ke ntfy diganti tiruan, dan satu uji memakai server HTTP lokal."""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartrt import core, create_app, ntfy_push, telegram_bot  # noqa: E402

PW = {"admin": "Admin#2026", "ketua": "Ketua#2026", "warga": "Warga#2026"}
TOKEN = "123456:TOKEN-PALSU"
HDR = {"X-Telegram-Bot-Api-Secret-Token": telegram_bot._webhook_secret(TOKEN)}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    core._FAILS.clear()
    ntfy_push._TOPIK_SEMENTARA = ""
    terkirim = []                                           # (server, payload) yang dikirim ke ntfy

    def post_palsu(server, payload, timeout=10):
        terkirim.append((server, payload))
        return 200, "{}"

    monkeypatch.setattr(ntfy_push, "_post", post_palsu)
    monkeypatch.setattr(telegram_bot, "_api", lambda *a, **k: {"ok": True, "result": {}})
    a = create_app({"DATABASE": str(tmp_path / "t.db"), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True,
                    "NTFY_UJI": True, "NTFY_ASYNC": False,
                    "NTFY_TOPIC_FILE": str(tmp_path / "ntfy_topic.txt"),
                    "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_IDS": "111", "TELEGRAM_ASYNC": False})
    a.terkirim = terkirim
    return a


def tok(c):
    with c.session_transaction() as s:
        return s["csrf"]


def login(app, user):
    c = app.test_client()
    c.get("/login")
    assert c.post("/login", data={"username": user, "password": PW[user], "csrf_token": tok(c)}).status_code == 302
    return c


def aktifkan(c, **data):
    return c.post("/api/darurat/aktifkan", json=data, headers={"X-CSRF-Token": tok(c)})


def test_topik_acak_dibuat_sekali_dan_stabil(app, tmp_path):
    with app.app_context():
        t1, t2 = ntfy_push.topik(), ntfy_push.topik()
    assert t1 == t2 and re.fullmatch(r"rukunin-[A-Za-z0-9_-]{20,}", t1) and len(t1) <= 64
    assert (tmp_path / "ntfy_topic.txt").read_text() == t1
    app.config["NTFY_TOPIC"] = "topik buatan!sendiri"                              # NTFY_TOPIC menang; karakter terlarang dibuang
    with app.app_context():
        assert ntfy_push.topik() == "topikbuatansendiri"


def test_alarm_web_dikirim_ke_ntfy_dengan_prioritas_tertinggi(app):
    w = login(app, "warga")
    assert aktifkan(w, jenis="Kebakaran", pesan="Rumah no 5").get_json()["ok"] is True
    (server, p), = app.terkirim
    assert server == "https://ntfy.sh"
    assert p["priority"] == 5 and p["tags"] == ["rotating_light"] and re.fullmatch(r"rukunin-[A-Za-z0-9_-]+", p["topic"])
    assert "Kebakaran" in p["title"] and "Rumah no 5" in p["message"]

    app.terkirim.clear()
    k = login(app, "ketua")
    assert k.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(k)}).get_json()["ok"] is True
    (_, p), = app.terkirim
    assert p["priority"] == 3 and "dihentikan" in p["title"]                       # stop: notifikasi biasa, bukan alarm


def test_alarm_dari_telegram_juga_dikirim_ke_ntfy(app):
    update = {"update_id": 1, "message": {"date": int(time.time()), "text": "ada bahaya", "chat": {"id": 111, "type": "private"},
                                          "from": {"username": "budi"}}}
    assert app.test_client().post("/telegram/webhook", json=update, headers=HDR).status_code == 200
    (_, p), = app.terkirim
    assert p["priority"] == 5 and "Darurat via Telegram" in p["title"] and "@budi" in p["message"]


def test_ntfy_bermasalah_atau_dimatikan_tidak_mengganggu_alarm(app, monkeypatch):
    monkeypatch.setattr(ntfy_push, "_post", lambda *a, **k: (0, "tidak ada internet"))
    w = login(app, "warga")
    assert aktifkan(w, jenis="Banjir").get_json()["ok"] is True                    # alarm tetap menyala

    k = login(app, "ketua")
    k.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(k)})
    app.config["NTFY_MODE"] = "off"
    monkeypatch.setattr(ntfy_push, "_post", lambda *a, **k: pytest.fail("tidak boleh mengirim saat NTFY_MODE=off"))
    assert aktifkan(w, jenis="Gempa").get_json()["ok"] is True
    r = k.post("/api/darurat/ntfy-tes", json={}, headers={"X-CSRF-Token": tok(k)})
    assert r.status_code == 400 and "dimatikan" in r.get_json()["pesan"]


def test_tombol_tes_dan_panel_hanya_untuk_ketua_admin(app, monkeypatch):
    k = login(app, "ketua")
    r = k.post("/api/darurat/ntfy-tes", json={}, headers={"X-CSRF-Token": tok(k)})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    (_, p), = app.terkirim
    assert p["priority"] == 5 and p["title"] == "Tes RUKUNIN"
    with app.app_context():
        topik = ntfy_push.topik()
    page = k.get("/darurat").data.decode()
    assert "cardNtfy" in page and topik in page and "ntfy://ntfy.sh/" + topik in page
    w = login(app, "warga")
    assert w.post("/api/darurat/ntfy-tes", json={}, headers={"X-CSRF-Token": tok(w)}).status_code == 403
    pw = w.get("/darurat").data.decode()
    assert "cardNtfy" not in pw and topik not in pw                                # topik rahasia tidak bocor ke warga biasa

    app.terkirim.clear()
    app.config["NTFY_ASYNC"] = False
    monkeypatch.setattr(ntfy_push, "_post", lambda *a, **k: (502, "bad gateway"))   # server ntfy menolak -> pesan jelas di tombol tes
    r = k.post("/api/darurat/ntfy-tes", json={}, headers={"X-CSRF-Token": tok(k)})
    assert r.status_code == 502 and "502" in r.get_json()["pesan"]


def test_post_sungguhan_ke_server_http_lokal():
    """Menjalankan _post asli terhadap server palsu di komputer ini: memastikan bentuk permintaan sesuai 'publish as JSON' ntfy."""
    diterima = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            diterima["path"] = self.path
            diterima["ctype"] = self.headers["Content-Type"]
            diterima["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        status, _ = ntfy_push._post("http://127.0.0.1:%d" % srv.server_port,
                                    {"topic": "t", "title": "🚨 Darurat", "message": "Halo", "priority": 5, "tags": ["rotating_light"]})
        assert status == 200
        assert diterima["path"] == "/" and diterima["ctype"] == "application/json"
        assert diterima["body"] == {"topic": "t", "title": "🚨 Darurat", "message": "Halo", "priority": 5, "tags": ["rotating_light"]}
    finally:
        srv.shutdown()
    assert ntfy_push._post("http://127.0.0.1:1", {"topic": "t"}, timeout=2)[0] == 0   # tidak ada server -> (0, pesan), tanpa error
