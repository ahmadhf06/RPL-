"""Tanda tangan digital surat: kode verifikasi + QR, gambar ttd Ketua, nama terkunci saat disetujui."""
import html
import io
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_smoke import PNG, app, login, post  # noqa: E402,F401


def _surat_selesai(app, w, s, k):
    r = post(w, "/surat/baru", {"jenis": "Surat Keterangan Domisili", "keperluan": "Pindah kerja"})
    sid = int(re.search(r"/surat/(\d+)", r.headers["Location"]).group(1))
    page = s.get(f"/surat/{sid}").data.decode()
    draf = html.unescape(re.search(r'name="draf"[^>]*>(.*?)</textarea>', page, re.S).group(1))
    nomor = re.search(r'name="nomor" id="nomor" value="([^"]+)"', page).group(1)
    post(s, f"/surat/{sid}/aksi", {"aksi": "teruskan", "nomor": nomor, "draf": draf})
    return sid, nomor


def _row(app, sid):
    con = sqlite3.connect(app.config["DATABASE"]); con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM surat WHERE id=?", (sid,)).fetchone()
    finally:
        con.close()


def test_ttd_digital_penuh(app):
    w, s, k, w2 = login(app, "warga"), login(app, "sekretaris"), login(app, "ketua"), login(app, "warga2")
    # Ketua unggah gambar tanda tangan; warga tidak boleh
    assert post(w, "/profil/ttd", {"ttd": (io.BytesIO(PNG), "t.png")}, content_type="multipart/form-data").status_code == 403
    assert post(k, "/profil/ttd", {"ttd": (io.BytesIO(PNG), "t.png")}, content_type="multipart/form-data").status_code == 302
    assert post(k, "/profil/ttd", {"ttd": (io.BytesIO(b"bukan gambar"), "t.png")}, content_type="multipart/form-data").status_code == 302
    assert b"Tanda tangan saat ini" in k.get("/profil").data

    sid, nomor = _surat_selesai(app, w, s, k)
    assert _row(app, sid)["ttd_token"] is None                       # belum disetujui -> belum ada kode
    assert b"DRAF" in s.get(f"/surat/{sid}/cetak").data
    post(k, f"/surat/{sid}/aksi", {"aksi": "setujui"})
    post(s, f"/surat/{sid}/aksi", {"aksi": "arsipkan"})
    r = _row(app, sid)
    assert len(r["ttd_token"]) == 32 and r["ttd_nama"] == "Hendra Wijaya" and r["ttd_gambar"]

    cetak = w.get(f"/surat/{sid}/cetak").data.decode()
    assert "<svg" in cetak and "ttd-img" in cetak and "Hendra Wijaya" in cetak
    assert f"/verifikasi/{r['ttd_token']}" in cetak
    # gambar ttd: pemilik surat & sekretaris boleh, warga lain tidak
    img = "/media/" + r["ttd_gambar"]
    assert w.get(img).status_code == 200 and s.get(img).status_code == 200 and w2.get(img).status_code == 403

    # halaman verifikasi publik (tanpa login), nama pemohon disamarkan
    pub = app.test_client().get(f"/verifikasi/{r['ttd_token']}")
    t = pub.data.decode()
    assert pub.status_code == 200 and nomor in t and "Hendra Wijaya" in t and "Surat ini sah" in t
    assert "Budi" not in t or "B***" in t
    assert app.test_client().get("/verifikasi/" + "0" * 32).status_code == 404
    assert app.test_client().get("/verifikasi/xyz").status_code == 404


def test_nama_lama_tetap_setelah_ketua_diganti(app):
    w, s, k = login(app, "warga"), login(app, "sekretaris"), login(app, "ketua")
    sid, _ = _surat_selesai(app, w, s, k)
    post(k, f"/surat/{sid}/aksi", {"aksi": "setujui"})
    post(s, f"/surat/{sid}/aksi", {"aksi": "arsipkan"})
    con = sqlite3.connect(app.config["DATABASE"])
    con.execute("UPDATE users SET nama='Ketua Baru' WHERE username='ketua'"); con.commit(); con.close()
    cetak = w.get(f"/surat/{sid}/cetak").data.decode()
    assert "Hendra Wijaya" in cetak and "Ketua Baru" not in cetak     # surat lama tidak ikut berubah
    sid2, _ = _surat_selesai(app, w, s, k)
    k2 = login(app, "ketua")
    post(k2, f"/surat/{sid2}/aksi", {"aksi": "setujui"})
    assert _row(app, sid2)["ttd_nama"] == "Ketua Baru"                 # surat baru memakai nama baru


def test_migrasi_db_lama_mengisi_kode_surat_disetujui(tmp_path):
    from smartrt import create_app, core
    db = str(tmp_path / "lama.db")
    a = create_app({"DATABASE": db, "UPLOAD_FOLDER": str(tmp_path / "u"), "TESTING": True})
    con = sqlite3.connect(db)
    con.execute("INSERT INTO surat(warga_id,jenis,keperluan,status,nomor,draf) VALUES(1,'X','Y','selesai','1/A','d')")
    # tiru database lama: tabel surat tanpa kolom tanda tangan
    cols = "id,warga_id,jenis,keperluan,keterangan,status,nomor,draf,catatan,created_at,updated_at"
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute(f"CREATE TABLE surat_x AS SELECT {cols} FROM surat")
    con.execute("DROP TABLE surat")
    con.execute("ALTER TABLE surat_x RENAME TO surat")
    con.execute("ALTER TABLE users DROP COLUMN ttd_gambar"); con.commit(); con.close()
    with a.app_context():
        core.init_db()
    con = sqlite3.connect(db)
    tok, nama = con.execute("SELECT ttd_token, ttd_nama FROM surat WHERE nomor='1/A'").fetchone()
    con.close()
    assert tok and len(tok) == 32 and nama == "Hendra Wijaya"


def test_ttd_dari_pdf(app):
    import pymupdf
    doc = pymupdf.open(); pg = doc.new_page()
    pg.draw_polyline([(200, 300), (240, 260), (270, 320), (320, 270), (380, 310)], color=(0, 0, 0.5), width=3)
    pdf = doc.tobytes()
    k = login(app, "ketua")
    r = post(k, "/profil/ttd", {"ttd": (io.BytesIO(pdf), "ttd.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 302
    con = sqlite3.connect(app.config["DATABASE"])
    nama = con.execute("SELECT ttd_gambar FROM users WHERE username='ketua'").fetchone()[0]
    con.close()
    assert nama and nama.endswith(".png")
    data = open(os.path.join(app.config["UPLOAD_FOLDER"], nama), "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pix = pymupdf.Pixmap(data)
    assert pix.width < 400 * 4 and pix.height < 120 * 4 and pix.width > pix.height   # terpotong rapat, bukan satu halaman A4
    assert b"Tanda tangan saat ini" in k.get("/profil").data
    # PDF rusak / bukan PDF sungguhan ditolak, ttd lama tetap
    post(k, "/profil/ttd", {"ttd": (io.BytesIO(b"%PDF-1.4 rusak"), "x.pdf")}, content_type="multipart/form-data")
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT ttd_gambar FROM users WHERE username='ketua'").fetchone()[0] == nama
    con.close()
