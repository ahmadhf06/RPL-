"""Foto profil: unggah, tampil di halaman, hapus, dan proteksi akses."""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_smoke import PNG, app, login, post, tok  # noqa: E402,F401


def _foto(app, user="warga"):
    con = sqlite3.connect(app.config["DATABASE"])
    try:
        return con.execute("SELECT foto FROM users WHERE username=?", (user,)).fetchone()[0]
    finally:
        con.close()


def test_panel_toggle_ada_di_panah_bukan_di_pencarian(app):
    c = login(app, "warga")
    html = c.get("/").get_data(as_text=True)
    assert 'id="panelToggle"' in html and "data-toggle-panel" in html
    topbar = re.search(r'<header class="topbar">.*?</header>', html, re.S).group(0)
    assert "data-toggle-panel" not in topbar          # tombol di samping pencarian sudah dihapus


def test_unggah_dan_hapus_foto(app):
    c = login(app, "warga")
    assert "avatar-default.svg" in c.get("/").get_data(as_text=True)
    r = post(c, "/profil/foto", {"foto": (__import__("io").BytesIO(PNG), "a.png")},
             headers={"X-Requested-With": "fetch"}, content_type="multipart/form-data")
    j = r.get_json()
    assert j["ok"] and j["url"].startswith("/avatar/")
    name = _foto(app)
    assert name and os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], name))
    assert j["url"] in c.get("/").get_data(as_text=True)          # tampil di kartu pengguna & panel
    assert c.get(j["url"]).status_code == 200
    # pengguna lain yang login boleh melihat; tanpa login ditolak
    assert login(app, "ketua").get(j["url"]).status_code == 200
    assert app.test_client().get(j["url"]).status_code in (302, 401, 403)
    # hapus
    r = post(c, "/profil/foto", {"hapus": "1"}, headers={"X-Requested-With": "fetch"})
    assert r.get_json()["ok"] and _foto(app) is None
    assert not os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], name))


def test_foto_bukan_gambar_ditolak(app):
    c = login(app, "warga")
    r = post(c, "/profil/foto", {"foto": (__import__("io").BytesIO(b"<?php echo 1;"), "x.png")},
             headers={"X-Requested-With": "fetch"}, content_type="multipart/form-data")
    assert r.status_code == 400 and not r.get_json()["ok"]
    assert _foto(app) is None


def test_avatar_nama_tidak_valid_404(app):
    c = login(app, "warga")
    assert c.get("/avatar/../../etc/passwd").status_code == 404
    assert c.get("/avatar/" + "0" * 32 + ".png").status_code == 404


def test_alarm_global_dimuat_di_semua_halaman(app):
    c = login(app, "warga")
    for url in ("/", "/profil", "/pengumuman"):
        r = c.get(url)
        if r.status_code == 200:
            h = r.get_data(as_text=True)
            assert "js/alarm.js" in h and "window.RUKUNIN" in h


def test_migrasi_kolom_foto_pada_db_lama(tmp_path):
    from smartrt import create_app
    db = str(tmp_path / "lama.db")
    a = create_app({"DATABASE": db, "UPLOAD_FOLDER": str(tmp_path / "u"), "TESTING": True})
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE users DROP COLUMN foto")      # tiru database lama
    con.commit(); con.close()
    with a.app_context():
        from smartrt import core
        core.init_db()
    con = sqlite3.connect(db)
    assert "foto" in [r[1] for r in con.execute("PRAGMA table_info(users)")]
    con.close()
