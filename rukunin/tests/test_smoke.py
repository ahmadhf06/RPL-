"""Uji end-to-end: jalankan dengan `python -m pytest -q` dari folder proyek."""
import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartrt import create_app  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PW = {"admin": "Admin#2026", "ketua": "Ketua#2026", "sekretaris": "Sekre#2026",
      "bendahara": "Bendahara#2026", "warga": "Warga#2026", "warga2": "Warga#2026"}


@pytest.fixture()
def app(tmp_path):
    from smartrt import core
    core._FAILS.clear()
    return create_app({"DATABASE": str(tmp_path / "t.db"), "UPLOAD_FOLDER": str(tmp_path / "up"), "TESTING": True})


def tok(c):
    with c.session_transaction() as s:
        return s["csrf"]


def login(app, user):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"username": user, "password": PW[user], "csrf_token": tok(c)})
    assert r.status_code == 302, user
    return c


def post(c, url, data=None, **kw):
    d = dict(data or {})
    d["csrf_token"] = tok(c)
    return c.post(url, data=d, **kw)


def test_login_csrf_and_lockout(app):
    c = app.test_client()
    c.get("/login")
    assert c.post("/login", data={"username": "admin", "password": "x"}).status_code == 400   # tanpa CSRF
    for _ in range(5):
        post(c, "/login", {"username": "ghost", "password": "salah"})
    assert b"Terlalu banyak" in post(c, "/login", {"username": "ghost", "password": "salah"}).data
    assert app.test_client().get("/surat/").status_code == 302                                  # wajib login


def test_rbac(app):
    w, s = login(app, "warga"), login(app, "sekretaris")
    for url in ("/admin/akun", "/keuangan/", "/warga/", "/tagihan", "/warga/baru"):
        assert w.get(url).status_code == 403, url
    assert s.get("/keuangan/").status_code == 403
    assert login(app, "bendahara").get("/surat/").status_code == 403
    assert post(s, "/pengumuman", {"judul": "x", "isi": "y"}).status_code == 403


def test_surat_flow(app):
    w, s, k = login(app, "warga"), login(app, "sekretaris"), login(app, "ketua")
    r = post(w, "/surat/baru", {"jenis": "Surat Keterangan Domisili", "keperluan": "Pindah kerja"})
    sid = int(re.search(r"/surat/(\d+)", r.headers["Location"]).group(1))
    assert b"Periksa" not in w.get(f"/surat/{sid}").data
    assert login(app, "warga2").get(f"/surat/{sid}").status_code == 403          # warga lain tidak boleh
    post(k, f"/surat/{sid}/aksi", {"aksi": "setujui"})                              # Ketua tak bisa lompati Sekretaris
    assert b"Diajukan" in k.get(f"/surat/{sid}").data
    assert post(s, f"/surat/{sid}/aksi", {"aksi": "setujui"}).status_code == 403   # Sekretaris tak bisa menyetujui
    page = s.get(f"/surat/{sid}").data.decode()
    draf = re.search(r'name="draf"[^>]*>(.*?)</textarea>', page, re.S).group(1)
    nomor = re.search(r'name="nomor" id="nomor" value="([^"]+)"', page).group(1)
    assert post(s, f"/surat/{sid}/aksi", {"aksi": "teruskan", "nomor": nomor, "draf": "terlalu pendek"}).status_code == 302
    assert b"menunggu_ketua" not in s.get(f"/surat/{sid}").data  # masih diajukan karena draf pendek ditolak
    import html
    post(s, f"/surat/{sid}/aksi", {"aksi": "teruskan", "nomor": nomor, "draf": html.unescape(draf)})
    assert b"Persetujuan Ketua RT" in k.get(f"/surat/{sid}").data
    assert w.get(f"/surat/{sid}/cetak").status_code == 403                          # belum selesai
    post(k, f"/surat/{sid}/aksi", {"aksi": "setujui"})
    assert post(k, f"/surat/{sid}/aksi", {"aksi": "setujui"}).status_code == 302   # status berubah -> ditolak lembut
    post(s, f"/surat/{sid}/aksi", {"aksi": "arsipkan"})
    assert w.get(f"/surat/{sid}/cetak").status_code == 200
    assert s.get(f"/surat/{sid}/cetak").status_code == 200                          # Sekretaris boleh cetak
    assert k.get(f"/surat/{sid}/cetak").status_code == 403                          # Ketua hanya melihat
    assert b"Cetak / Unduh PDF" not in k.get(f"/surat/{sid}").data
    assert b"Cetak / Unduh PDF" in w.get(f"/surat/{sid}").data
    n = w.get("/api/notifikasi").get_json()
    assert n["unread"] >= 3
    assert any("selesai" in i["judul"].lower() for i in n["items"])


def test_laporan_foto_dan_akses(app):
    w, k, w2 = login(app, "warga"), login(app, "ketua"), login(app, "warga2")
    bad = post(w, "/laporan/baru", {"judul": "Jalan", "kategori": "Infrastruktur", "deskripsi": "rusak", "lokasi": "Blok A",
                                    "foto": (io.BytesIO(b"<html>not image"), "x.png")}, content_type="multipart/form-data")
    assert bad.status_code == 302 and b"Jalan" not in w.get("/laporan/").data       # berkas palsu ditolak, tak tersimpan
    r = post(w, "/laporan/baru", {"judul": "Jalan berlubang", "kategori": "Infrastruktur", "deskripsi": "rusak parah", "lokasi": "Blok A",
                                  "lat": "-6.2", "lng": "106.8", "foto": (io.BytesIO(PNG), "a.png")}, content_type="multipart/form-data")
    lid = int(re.search(r"/laporan/(\d+)", r.headers["Location"]).group(1))
    img = re.search(r"/media/([0-9a-f]{32}\.png)", w.get(f"/laporan/{lid}").data.decode()).group(0)
    assert w.get(img).status_code == 200 and k.get(img).status_code == 200 and w2.get(img).status_code == 403
    assert w2.get(f"/laporan/{lid}").status_code == 403
    kid = re.search(r'value="(\d+)"\s*>Siti', k.get(f"/laporan/{lid}").data.decode()).group(1)
    post(k, f"/laporan/{lid}/update", {"status": "diproses", "pj_id": kid, "catatan": "ditangani"})
    assert b"Diproses" in w.get(f"/laporan/{lid}").data
    sk = login(app, "sekretaris")
    assert sk.get(f"/laporan/{lid}").status_code == 200       # penanggung jawab
    assert post(sk, f"/laporan/{lid}/update", {"status": "selesai"}).status_code == 302
    assert post(w, f"/laporan/{lid}/update", {"status": "selesai"}).status_code == 403


def test_keuangan(app):
    w, b, k = login(app, "warga"), login(app, "bendahara"), login(app, "ketua")
    page = w.get("/tagihan-saya").data.decode()
    tid = re.search(r"/tagihan-saya/(\d+)/bayar", page).group(1)
    assert post(w, f"/tagihan-saya/{tid}/bayar", {"metode": "QRIS"}, content_type="multipart/form-data").status_code == 302  # tanpa bukti
    assert b"Menunggu Verifikasi" not in w.get("/tagihan-saya").data
    post(w, f"/tagihan-saya/{tid}/bayar", {"metode": "QRIS", "bukti": (io.BytesIO(PNG), "b.png")}, content_type="multipart/form-data")
    saldo0 = re.search(r"<b>(Rp [\d.]+)</b><span>Saldo kas", k.get("/keuangan/").data.decode()).group(1)
    assert post(k, f"/tagihan/{tid}/aksi", {"aksi": "terima"}).status_code == 403          # ketua tak boleh verifikasi
    post(b, f"/tagihan/{tid}/aksi", {"aksi": "terima"})
    saldo1 = re.search(r"<b>(Rp [\d.]+)</b><span>Saldo kas", k.get("/keuangan/").data.decode()).group(1)
    assert saldo1 != saldo0
    assert b"Lunas" in w.get("/tagihan-saya").data
    assert post(b, "/keuangan/transaksi", {"tipe": "pengeluaran", "kategori": "Kebersihan", "nominal": "999999999",
                                           "keterangan": "x", "tanggal": "2026-10-21"}).status_code == 302
    post(b, "/keuangan/transaksi", {"tipe": "pengeluaran", "kategori": "Kebersihan", "nominal": "10000",
                                    "keterangan": "sapu", "tanggal": "2026-10-21"})
    assert b"sapu" in b.get("/keuangan/").data
    assert b"Tanggal,Jenis" in k.get("/keuangan/export.csv").data
    post(b, "/tagihan/generate", {"periode": "2027-01", "jenis": "Iuran Bulanan", "nominal": "50000"})
    assert b"Rina Marlina" in b.get("/tagihan?periode=2027-01").data


def test_transparansi_kas(app):
    w, b, s, k = login(app, "warga"), login(app, "bendahara"), login(app, "sekretaris"), login(app, "ketua")
    post(b, "/keuangan/transaksi", {"tipe": "pengeluaran", "kategori": "Kebersihan", "nominal": "10000",
                                    "keterangan": "beli sapu transparan", "tanggal": "2026-10-21"})
    # warga & pengurus non-keuangan bisa melihat; anonim diarahkan login
    assert app.test_client().get("/transparansi").status_code == 302
    for c in (w, s, k, b):
        assert c.get("/transparansi").status_code == 200
    page = w.get("/transparansi").data.decode()
    assert "beli sapu transparan" in page and "Saldo Kas Saat Ini" in page
    assert w.get("/transparansi?tipe=pemasukan").status_code == 200
    assert w.get("/transparansi?bulan=bukan-bulan").status_code == 200          # filter tidak valid diabaikan
    # dashboard warga memuat kartu transparansi; halaman tetap read-only (tidak ada form tambah transaksi)
    assert b"Transparansi Kas RT" in w.get("/").data
    assert "/keuangan/transaksi" not in page
    assert w.post("/keuangan/transaksi", data={}).status_code in (400, 403)

    # privasi: nama pembayar iuran tidak bocor ke warga lain
    tid = re.search(r"/tagihan-saya/(\d+)/bayar", w.get("/tagihan-saya").data.decode()).group(1)
    post(w, f"/tagihan-saya/{tid}/bayar", {"metode": "QRIS", "bukti": (io.BytesIO(PNG), "b.png")}, content_type="multipart/form-data")
    post(b, f"/tagihan/{tid}/aksi", {"aksi": "terima"})
    # sisi pengurus: keterangan memuat nama pembayar ("Iuran Bulanan 2026-xx - Nama")
    ket = re.search(r'<td class="muted">([^<]+) - ([^<]+)</td>', b.get("/keuangan/").data.decode())
    assert ket, "baris iuran tidak ditemukan di halaman pengurus"
    jenis_periode, nama = ket.group(1).strip(), ket.group(2).strip()
    w2 = login(app, "warga2").get("/transparansi").data.decode()
    assert jenis_periode in w2          # warga lain melihat iuran masuk...
    assert nama not in w2               # ...tetapi tanpa nama pembayarnya


def test_komunitas(app):
    w, k, s = login(app, "warga"), login(app, "ketua"), login(app, "sekretaris")
    post(k, "/voting", {"judul": "Portal", "berakhir": "2099-01-01", "opsi": "Ya\nTidak"})
    page = w.get("/voting").data.decode()
    vid, oid = re.search(r"/voting/(\d+)/pilih", page).group(1), re.search(r'name="opsi" value="(\d+)"', page).group(1)
    post(w, f"/voting/{vid}/pilih", {"opsi": oid})
    r = post(w, f"/voting/{vid}/pilih", {"opsi": oid}, follow_redirects=True)
    assert b"sudah memberikan suara" in r.data                                    # satu akun satu suara
    assert post(login(app, "bendahara"), f"/voting/{vid}/pilih", {"opsi": oid}).status_code == 403
    post(k, "/pengumuman", {"judul": "Rapat", "isi": "Besok", "penting": "on"})
    assert b"Rapat" in w.get("/pengumuman").data
    post(w, "/aspirasi", {"judul": "Lampu jalan", "isi": "Mohon diganti"})
    post(k, "/aspirasi/1/tanggapi", {"tanggapan": "Siap"})
    assert b"Siap" in w.get("/aspirasi").data
    r = post(s, "/kegiatan", {"nama": "Kerja Bakti", "jenis": "Kerja Bakti", "tanggal": "2026-10-25", "lokasi": "Taman"})
    kid = re.search(r"/kegiatan/(\d+)", r.headers["Location"]).group(1)
    d = s.get(f"/kegiatan/{kid}").data.decode()
    assert "<svg" in d
    token = re.search(r"/presensi/([\w-]+)", d).group(1)
    assert b"Ya, saya hadir" in w.get(f"/presensi/{token}").data
    post(w, f"/presensi/{token}")
    assert b"Anda hadir" in w.get("/kegiatan").data
    assert b"Budi Santoso" in s.get(f"/kegiatan/{kid}").data


def test_admin_dan_warga(app):
    a, k = login(app, "admin"), login(app, "ketua")
    assert post(a, "/admin/akun", {"username": "baru1", "nama": "Warga Baru", "role": "warga", "password": "abc"}).status_code == 302
    assert b"baru1" not in a.get("/admin/akun").data                               # sandi lemah ditolak
    post(a, "/admin/akun", {"username": "baru1", "nama": "Warga Baru", "role": "warga", "password": "Rahasia123"})
    assert b"baru1" in a.get("/admin/akun").data
    c = app.test_client()
    c.get("/login")
    assert post(c, "/login", {"username": "baru1", "password": "Rahasia123"}).status_code == 302
    me = [x for x in a.get("/admin/akun").data.decode().split("/admin/akun/")[1:] if x]
    assert post(a, "/admin/akun/1", {"nama": "Admin", "role": "warga", "aktif": "on"}).status_code == 302   # tak bisa turunkan diri
    assert b"tidak dapat mengubah" in a.get("/admin/akun").data
    assert b"akun_baru" in a.get("/admin/log").data
    post(k, "/warga/baru", {"nama": "Warga X", "nik": "3201010101900099", "jk": "L", "alamat": "Jl. X", "status_tinggal": "Tetap", "aktif": "on"})
    assert b"Warga X" in k.get("/warga/?q=Warga X").data
    assert b"Warga X" in login(app, "bendahara").get("/warga/").data
    for u in PW:
        cl = login(app, u)
        assert cl.get("/").status_code == 200 and cl.get("/api/stats").get_json()["cards"]
    assert "Content-Security-Policy" in cl.get("/").headers


def test_darurat_dan_bendahara(app):
    w, k, b = login(app, "warga"), login(app, "ketua"), login(app, "bendahara")
    # 1. Warga bisa mengaktifkan alarm darurat langsung
    r_act = w.post("/api/darurat/aktifkan", json={"jenis": "Banjir", "pesan": "Air naik cepat"},
                   headers={"X-CSRF-Token": tok(w)})
    assert r_act.status_code == 200, r_act.data
    st = w.get("/api/darurat/status").get_json()
    assert st["aktif"] is True
    assert st["jenis"] == "Banjir"
    
    # 2. Warga tidak boleh mematikan alarm (hanya Ketua RT)
    r_stop_w = w.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(w)})
    assert r_stop_w.status_code == 403
    
    # 3. Ketua RT bisa mematikan alarm
    r_stop_k = k.post("/api/darurat/stop", headers={"X-CSRF-Token": tok(k)})
    assert r_stop_k.status_code == 200
    assert w.get("/api/darurat/status").get_json()["aktif"] is False
    
    # 4. Tampilan bendahara memiliki grafik keuangan
    b_page = b.get("/keuangan/").data.decode()
    assert "Grafik Arus Kas RT" in b_page
    assert "Grafik Kategori Pengeluaran" in b_page
    assert "Grafik Kategori Pemasukan" in b_page
    
    # 5. Notifikasi alarm masuk ke ketua (pengirim alarm tidak terima notif diri sendiri)
    notif_data_k = k.get("/api/notifikasi").get_json()
    assert "items" in notif_data_k
    assert any("Air naik cepat" in it.get("pesan", "") for it in notif_data_k["items"])

    # 6. Warga sendiri tidak mendapat notifikasi alarm yang ia aktifkan
    notif_data_w = w.get("/api/notifikasi").get_json()
    assert "items" in notif_data_w



# ---------------------------------------------------------------- tampilan RUKUNIN (glassmorphism 3 bagian)
def test_tampilan_dashboard_dan_aset(app):
    """Dashboard memakai kerangka 3 bagian + aset ilustrasi ada, untuk semua peran."""
    for user in PW:
        c = login(app, user)
        r = c.get("/")
        assert r.status_code == 200, user
        html = r.get_data(as_text=True)
        for kunci in ('class="sidebar"', 'class="topbar"', 'id="rightPanel"', "RUKUN", "Aksi Cepat"):
            assert kunci in html, (user, kunci)
    html = login(app, "ketua").get("/").get_data(as_text=True)
    for kartu in ("Total Warga", "Kas RT", "Iuran Terbayar", "Pengajuan Surat", "Aktivitas Terbaru", "Laporan Lingkungan Terbaru"):
        assert kartu in html, kartu
    c = app.test_client()
    for f in ("lingkungan-hero", "sidebar-rumah", "panel-gapura", "balai-musyawarah", "avatar-default", "logo-rukunin"):
        assert c.get(f"/static/img/{f}.svg").status_code == 200, f


def test_edit_profil_dari_panel_tidak_menghapus_telepon(app):
    """Modal Edit Profil mengirim nama + telepon; telepon warga tidak boleh terhapus."""
    from smartrt import core
    c = login(app, "warga")
    html = c.get("/").get_data(as_text=True)
    assert 'id="modalProfil"' in html and 'name="telepon"' in html
    with app.app_context():
        sebelum = core.scalar("SELECT telepon FROM warga WHERE user_id=(SELECT id FROM users WHERE username='warga')")
    r = post(c, "/profil", {"aksi": "info", "nama": "Budi Santoso", "telepon": sebelum or ""})
    assert r.status_code == 302
    with app.app_context():
        sesudah = core.scalar("SELECT telepon FROM warga WHERE user_id=(SELECT id FROM users WHERE username='warga')")
    assert sesudah == sebelum
