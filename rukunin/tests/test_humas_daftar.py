"""Uji role Humas, pendaftaran warga mandiri, login tanpa akun uji, dan migrasi database lama.
Jalankan:  python -m pytest -q tests/test_humas_daftar.py"""
import io
import os
import re
import shutil
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartrt import create_app, core  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PW = {"admin": "Admin#2026", "ketua": "Ketua#2026", "sekretaris": "Sekre#2026", "bendahara": "Bendahara#2026",
      "humas": "Humas#2026", "warga": "Warga#2026", "warga2": "Warga#2026"}


@pytest.fixture()
def app(tmp_path):
    core._FAILS.clear()
    core._HITS.clear()
    return create_app({"DATABASE": str(tmp_path / "t.db"), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True})


def tok(c):
    with c.session_transaction() as s:
        return s["csrf"]


def login(app, user, pw=None):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"username": user, "password": pw or PW[user], "csrf_token": tok(c)})
    assert r.status_code == 302, user
    return c


def post(c, url, data=None, **kw):
    d = dict(data or {})
    d["csrf_token"] = tok(c)
    return c.post(url, data=d, **kw)


def form_daftar(**ov):
    d = dict(username="calon1", password="Rahasia123", konfirmasi="Rahasia123", nama="Calon Warga Satu",
             nik="3201010101950001", kk="3201010101000001", jk="L", tempat_lahir="Bekasi", tgl_lahir="1995-01-01",
             alamat="Jl. Melati No. 9", telepon="081234567890", pekerjaan="Guru", status_tinggal="Tetap")
    d.update(ov)
    return d


def kirim_daftar(app, c=None, files=True, **ov):
    if c is None:
        c = app.test_client()
        c.get("/daftar")
    d = form_daftar(**ov)
    d["csrf_token"] = tok(c)
    if files:
        d["foto_ktp"] = (io.BytesIO(PNG), "ktp.png")
        d["foto_kk"] = (io.BytesIO(PNG), "kk.png")
    return c, c.post("/daftar", data=d, content_type="multipart/form-data")


# ---------------------------------------------------------------- login biasa (tanpa akun uji / auto isi)
def test_login_tanpa_akun_uji(app):
    html = app.test_client().get("/login").data.decode()
    assert "data-demo" not in html and "Akun uji" not in html and "Warga#2026" not in html
    assert "/daftar" in html                                       # tautan pendaftaran tersedia
    js = open(os.path.join(app.root_path, "static", "js", "app.js"), encoding="utf-8").read()
    assert "data-demo" not in js


def test_pendaftaran_bisa_ditutup(app):
    app.config["ALLOW_REGISTRATION"] = False
    c = app.test_client()
    assert c.get("/daftar").status_code == 302
    assert b"/daftar" not in c.get("/login").data


# ---------------------------------------------------------------- role Humas
def test_humas_rbac(app):
    h, k = login(app, "humas"), login(app, "ketua")
    for url in ("/warga/", "/keuangan/", "/tagihan", "/surat/", "/admin/akun", "/pendaftaran", "/warga/baru"):
        assert h.get(url).status_code == 403, url
    for url in ("/", "/pengumuman", "/aspirasi", "/kegiatan", "/ronda", "/voting", "/laporan/", "/darurat"):
        assert h.get(url).status_code in (200, 302), url
    # Humas tidak punya aksi Ketua: voting, persetujuan surat, verifikasi pendaftaran
    assert post(h, "/voting", {"judul": "x", "berakhir": "2099-01-01", "opsi": "a\nb"}).status_code == 403
    assert post(h, "/voting/1/tutup").status_code == 403
    assert post(h, "/surat/1/aksi", {"aksi": "setujui"}).status_code == 403
    assert post(h, "/pendaftaran/1/aksi", {"aksi": "setujui"}).status_code == 403
    assert post(h, "/warga/baru", {}).status_code == 403
    # Pengumuman: buat sendiri, hapus miliknya, tidak boleh hapus milik Ketua
    r = post(h, "/pengumuman", {"judul": "Info Humas", "isi": "Kerja bakti Minggu"})
    assert r.status_code == 302
    con = sqlite3.connect(app.config["DATABASE"])
    mine = con.execute("SELECT id FROM pengumuman WHERE judul='Info Humas'").fetchone()[0]
    ketua_p = con.execute("SELECT id FROM pengumuman WHERE author_id=(SELECT id FROM users WHERE username='ketua') LIMIT 1").fetchone()[0]
    assert post(h, f"/pengumuman/{ketua_p}/hapus").status_code == 403
    assert post(h, f"/pengumuman/{mine}/hapus").status_code == 302
    assert post(k, f"/pengumuman/{ketua_p}/hapus").status_code == 302      # Ketua tetap boleh hapus apa pun


def test_humas_aspirasi_kegiatan_laporan(app):
    w, h, k = login(app, "warga"), login(app, "humas"), login(app, "ketua")
    post(w, "/aspirasi", {"judul": "Lampu jalan mati", "isi": "Mohon diperbaiki"})
    assert b"Lampu jalan mati" in h.get("/aspirasi").data
    aid = sqlite3.connect(app.config["DATABASE"]).execute("SELECT id FROM aspirasi").fetchone()[0]
    assert post(h, f"/aspirasi/{aid}/tanggapi", {"tanggapan": "Sudah kami teruskan"}).status_code == 302
    assert b"Sudah kami teruskan" in w.get("/aspirasi").data
    assert login(app, "bendahara").get("/aspirasi").status_code == 403                 # peran lain tetap tertutup
    # Humas membuat kegiatan + QR presensi
    r = post(h, "/kegiatan", {"nama": "Rapat Humas", "jenis": "Rapat", "tanggal": "2099-01-01", "lokasi": "Balai"})
    assert r.status_code == 302 and "/kegiatan/" in r.headers["Location"]
    assert h.get(r.headers["Location"]).status_code == 200
    # Laporan: Ketua menunjuk Humas sebagai PJ, Humas dapat menindaklanjuti
    post(w, "/laporan/baru", {"judul": "Got mampet", "kategori": "Kebersihan", "deskripsi": "Banjir kecil", "lokasi": "Gang 2"})
    con = sqlite3.connect(app.config["DATABASE"])
    lid = con.execute("SELECT id FROM laporan").fetchone()[0]
    hid = con.execute("SELECT id FROM users WHERE username='humas'").fetchone()[0]
    assert h.get(f"/laporan/{lid}").status_code == 403                                 # belum ditunjuk
    post(k, f"/laporan/{lid}/update", {"status": "diproses", "pj_id": hid})
    assert h.get(f"/laporan/{lid}").status_code == 200
    assert post(h, f"/laporan/{lid}/update", {"status": "selesai", "catatan": "Beres"}).status_code == 302
    # Alarm darurat boleh dinyalakan Humas (seperti peran lain), tetapi tidak boleh dimatikan
    assert h.post("/api/darurat/aktifkan", json={}, headers={"X-CSRF-Token": tok(h)}).status_code == 200
    assert h.post("/api/darurat/stop", json={}, headers={"X-CSRF-Token": tok(h)}).status_code == 403


def test_admin_bisa_buat_akun_humas(app):
    a = login(app, "admin")
    assert b"Humas" in a.get("/admin/akun").data
    assert post(a, "/admin/akun", {"username": "humas2", "nama": "Humas Dua", "role": "humas",
                                    "password": "Humas#2027"}).status_code == 302
    assert login(app, "humas2", "Humas#2027").get("/aspirasi").status_code == 200


# ---------------------------------------------------------------- pendaftaran warga mandiri
def test_alur_daftar_setujui(app):
    c, r = kirim_daftar(app)
    assert r.status_code == 302 and r.headers["Location"].endswith("/daftar/terkirim")
    con = sqlite3.connect(app.config["DATABASE"])
    uid, aktif, role = con.execute("SELECT id, aktif, role FROM users WHERE username='calon1'").fetchone()
    assert (aktif, role) == (0, "warga")                                   # akun belum aktif, peran dikunci 'warga'
    assert con.execute("SELECT COUNT(*) FROM warga WHERE nik='3201010101950001'").fetchone()[0] == 0   # belum jadi warga

    # belum bisa masuk; pemilik akun melihat statusnya
    c2 = app.test_client()
    c2.get("/login")
    r = c2.post("/login", data={"username": "calon1", "password": "Rahasia123", "csrf_token": tok(c2)})
    assert r.status_code == 200 and b"menunggu verifikasi" in r.data
    r = c2.post("/login", data={"username": "calon1", "password": "salah", "csrf_token": tok(c2)})
    assert b"menunggu verifikasi" not in r.data                            # kata sandi salah tidak membocorkan status

    # data & dokumen masuk ke Ketua RT (dan notifikasi)
    k = login(app, "ketua")
    assert k.get("/").status_code == 200 and b"Pendaftaran Warga" in k.get("/pendaftaran").data
    pid, ktp = con.execute("SELECT id, foto_ktp FROM pendaftaran WHERE username='calon1'").fetchone()
    assert con.execute("SELECT COUNT(*) FROM notifikasi n JOIN users u ON u.id=n.user_id WHERE u.username='ketua' "
                       "AND n.judul='Pendaftaran warga baru'").fetchone()[0] == 1
    d = k.get(f"/pendaftaran/{pid}")
    assert d.status_code == 200 and b"3201010101950001" in d.data and ktp.encode() in d.data
    assert k.get(f"/media/{ktp}").status_code == 200                      # Ketua boleh melihat KTP
    for siapa in ("humas", "sekretaris", "bendahara", "warga", "admin"):   # peran lain tidak boleh
        assert login(app, siapa).get(f"/media/{ktp}").status_code == 403, siapa
    assert app.test_client().get(f"/media/{ktp}").status_code == 302       # anonim: diarahkan ke login

    # Admin tidak boleh melewati verifikasi dengan mengaktifkan akun langsung
    a = login(app, "admin")
    post(a, f"/admin/akun/{uid}", {"nama": "Calon Warga Satu", "role": "warga", "aktif": "on"})
    assert con.execute("SELECT aktif FROM users WHERE id=?", (uid,)).fetchone()[0] == 0

    # Ketua menyetujui
    assert post(k, f"/pendaftaran/{pid}/aksi", {"aksi": "setujui"}).status_code == 302
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT aktif FROM users WHERE id=?", (uid,)).fetchone()[0] == 1
    w = con.execute("SELECT user_id, nama, alamat, telepon, status_tinggal FROM warga WHERE nik='3201010101950001'").fetchone()
    assert w == (uid, "Calon Warga Satu", "Jl. Melati No. 9", "081234567890", "Tetap")
    assert post(k, f"/pendaftaran/{pid}/aksi", {"aksi": "setujui"}).status_code == 302     # diproses dua kali -> ditolak sistem
    assert con.execute("SELECT COUNT(*) FROM warga WHERE nik='3201010101950001'").fetchone()[0] == 1

    # Sekarang dapat masuk sebagai warga biasa
    n = login(app, "calon1", "Rahasia123")
    assert n.get("/surat/baru").status_code == 200 and n.get("/pendaftaran").status_code == 403


def test_daftar_tolak_lalu_daftar_ulang(app):
    kirim_daftar(app)
    con = sqlite3.connect(app.config["DATABASE"])
    pid = con.execute("SELECT id FROM pendaftaran").fetchone()[0]
    k = login(app, "ketua")
    assert post(k, f"/pendaftaran/{pid}/aksi", {"aksi": "tolak"}).status_code == 302
    assert con.execute("SELECT status FROM pendaftaran WHERE id=?", (pid,)).fetchone()[0] == "menunggu"   # alasan wajib
    post(k, f"/pendaftaran/{pid}/aksi", {"aksi": "tolak", "catatan": "Foto KTP buram"})
    c2 = app.test_client()
    c2.get("/login")
    r = c2.post("/login", data={"username": "calon1", "password": "Rahasia123", "csrf_token": tok(c2)})
    assert b"Foto KTP buram" in r.data
    # daftar ulang dengan username yang sama diperbolehkan setelah ditolak
    _, r = kirim_daftar(app, nik="3201010101950001")
    assert r.status_code == 302
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT COUNT(*) FROM pendaftaran").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM users WHERE username='calon1'").fetchone()[0] == 1


def test_daftar_hubungkan_ke_data_warga_yang_ada(app):
    # Joko Susilo sudah didata Ketua (tanpa akun); NIK-nya ada di seed.
    con = sqlite3.connect(app.config["DATABASE"])
    nik, nama = con.execute("SELECT nik, nama FROM warga WHERE user_id IS NULL LIMIT 1").fetchone()
    kirim_daftar(app, nik=nik, username="joko1")
    pid = con.execute("SELECT id FROM pendaftaran").fetchone()[0]
    k = login(app, "ketua")
    assert nama.encode() in k.get(f"/pendaftaran/{pid}").data
    n_awal = con.execute("SELECT COUNT(*) FROM warga").fetchone()[0]
    post(k, f"/pendaftaran/{pid}/aksi", {"aksi": "setujui"})
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT COUNT(*) FROM warga").fetchone()[0] == n_awal            # tidak digandakan
    assert con.execute("SELECT u.username FROM warga w JOIN users u ON u.id=w.user_id WHERE w.nik=?", (nik,)).fetchone()[0] == "joko1"


def test_daftar_validasi(app):
    con = sqlite3.connect(app.config["DATABASE"])

    def jumlah():
        return con.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM pendaftaran)").fetchone()

    awal = jumlah()
    kasus = [dict(username="ab"), dict(username="a b!"), dict(username="warga"),                  # username buruk / sudah dipakai
             dict(password="abc", konfirmasi="abc"), dict(password="12345678", konfirmasi="12345678"),
             dict(konfirmasi="Beda12345"), dict(nik="123"), dict(nik="320101010190000X"),
             dict(nik="3201010101900001"),                                                         # NIK warga seed yang sudah punya akun
             dict(jk="X"), dict(tgl_lahir="31-02-2020"), dict(telepon="abc"), dict(nama=""), dict(alamat="")]
    for ov in kasus:
        _, r = kirim_daftar(app, **ov)
        assert r.status_code == 400, ov
    _, r = kirim_daftar(app, files=False)                                                          # KTP wajib
    assert r.status_code == 400 and b"Foto KTP" in r.data
    assert jumlah() == awal                                                                        # tidak ada yang tersimpan

    c = app.test_client()
    c.get("/daftar")
    d = form_daftar()
    d.update(csrf_token=tok(c), foto_ktp=(io.BytesIO(b"MZ\x90\x00 bukan gambar"), "ktp.png"))
    assert c.post("/daftar", data=d, content_type="multipart/form-data").status_code == 400        # isi bukan gambar
    d.update(foto_ktp=(io.BytesIO(PNG + b"\x00" * (5 * 1024 * 1024)), "besar.png"))
    assert c.post("/daftar", data=d, content_type="multipart/form-data").status_code in (400, 413)
    assert jumlah() == awal
    # Gagal di berkas kedua tidak boleh meninggalkan berkas pertama (berkas yatim)
    up = app.config["UPLOAD_FOLDER"]
    sebelum = set(os.listdir(up))
    d.update(foto_ktp=(io.BytesIO(PNG), "ktp.png"), foto_kk=(io.BytesIO(b"bukan gambar sama sekali"), "kk.png"))
    assert c.post("/daftar", data=d, content_type="multipart/form-data").status_code == 400
    assert set(os.listdir(up)) == sebelum and jumlah() == awal


def test_daftar_csrf_peran_dan_batas(app):
    c = app.test_client()
    c.get("/daftar")
    d = form_daftar(role="admin")
    d["foto_ktp"] = (io.BytesIO(PNG), "ktp.png")
    assert c.post("/daftar", data=d, content_type="multipart/form-data").status_code == 400       # tanpa CSRF
    # peran/aktif dari formulir tidak dipercaya
    d.update(csrf_token=tok(c), aktif="1", foto_ktp=(io.BytesIO(PNG), "ktp.png"))
    assert c.post("/daftar", data=d, content_type="multipart/form-data").status_code == 302
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT role, aktif FROM users WHERE username='calon1'").fetchone() == (("warga", 0))
    # Batas pendaftaran berhasil per IP: 5 per jam
    for i in range(2, 6):
        _, r = kirim_daftar(app, username=f"calon{i}", nik=f"32010101019500{i:02d}")
        assert r.status_code == 302, i
    _, r = kirim_daftar(app, username="calon6", nik="3201010101950099")
    assert r.status_code == 429


def test_dashboard_ketua_menampilkan_pendaftaran_menunggu(app):
    k = login(app, "ketua")
    assert b"Menunggu verifikasi Anda" not in k.get("/").data
    kirim_daftar(app)
    assert b"menunggu verifikasi Anda" in k.get("/").data


# ---------------------------------------------------------------- migrasi database lama (CHECK role tanpa 'humas')
def _buat_db_lama(path):
    """Bangun database dengan skema LAMA (sebelum Humas & pendaftaran) beserta data yang saling terhubung."""
    from smartrt.core import hash_pw
    sql = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "smartrt", "database", "schema.sql"),
               encoding="utf-8").read().split("-- Pendaftaran akun warga mandiri")[0]
    sql = sql.replace("'bendahara','humas','warga'", "'bendahara','warga'")
    con = sqlite3.connect(path)
    con.executescript(sql)
    assert "'humas'" not in con.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
    for i, (u, role) in enumerate([("admin", "admin"), ("ketua", "ketua"), ("warga", "warga")], 1):
        con.execute("INSERT INTO users(username,password_hash,nama,role) VALUES(?,?,?,?)", (u, hash_pw(PW[u]), u.title(), role))
    con.execute("INSERT INTO warga(user_id,nik,nama,jk,alamat) VALUES(3,'3201010101900001','Warga','L','Jl. A')")
    con.execute("INSERT INTO surat(warga_id,jenis,keperluan) VALUES(1,'Surat Keterangan Domisili','Pindah')")
    con.execute("INSERT INTO surat_log(surat_id,status,oleh) VALUES(1,'diajukan',3)")
    con.execute("INSERT INTO laporan(user_id,judul,kategori,deskripsi,lokasi,pj_id) VALUES(3,'L','Kebersihan','d','x',2)")
    con.execute("INSERT INTO notifikasi(user_id,judul) VALUES(3,'halo')")
    con.execute("INSERT INTO settings VALUES('nama_rt','RT 03 / RW 05')")
    con.commit()
    con.close()


def test_migrasi_database_lama(tmp_path):
    dst = tmp_path / "lama.db"
    _buat_db_lama(dst)
    con = sqlite3.connect(dst)
    sebelum = con.execute("SELECT id, username, role, password_hash, created_at FROM users ORDER BY id").fetchall()
    con.close()

    app = create_app({"DATABASE": str(dst), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True})
    con = sqlite3.connect(dst)
    assert "'humas'" in con.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
    assert con.execute("SELECT id, username, role, password_hash, created_at FROM users ORDER BY id").fetchall() == sebelum
    assert con.execute("SELECT COUNT(*) FROM warga").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM surat").fetchone()[0] == 1 and con.execute("SELECT COUNT(*) FROM surat_log").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM notifikasi").fetchone()[0] == 1 and con.execute("SELECT pj_id FROM laporan").fetchone()[0] == 2
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # Admin bisa membuat akun Humas di database hasil migrasi; migrasi tidak mengulang saat aplikasi dijalankan lagi
    a = login(app, "admin")
    post(a, "/admin/akun", {"username": "humas", "nama": "Humas RT", "role": "humas", "password": "Humas#2026"})
    assert login(app, "humas").get("/aspirasi").status_code == 200
    app2 = create_app({"DATABASE": str(dst), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True})
    assert sqlite3.connect(dst).execute("SELECT COUNT(*) FROM users WHERE role='humas'").fetchone()[0] == 1
    assert login(app2, "ketua").get("/").status_code == 200
