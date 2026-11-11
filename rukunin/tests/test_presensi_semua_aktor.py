import re
import pytest
from test_smoke import app, post, tok  # noqa: F401

PW = {
    "admin": "Admin#2026",
    "ketua": "Ketua#2026",
    "sekretaris": "Sekre#2026",
    "bendahara": "Bendahara#2026",
    "humas": "Humas#2026",
    "warga": "Warga#2026",
    "warga2": "Warga#2026",
}


def login_actor(app, user):
    c = app.test_client()
    c.get("/login")
    r = c.post("/login", data={"username": user, "password": PW[user], "csrf_token": tok(c)})
    assert r.status_code == 302, f"Gagal login sebagai {user}"
    return c


def test_presensi_qr_semua_aktor(app):
    """Memastikan menu, halaman presensi kegiatan, kode QR, dan presensi dapat diakses oleh semua aktor non-admin."""
    aktor_roles = [
        ("ketua", "Hendra Wijaya"),
        ("sekretaris", "Siti Rahma"),
        ("bendahara", "Agus Salim"),
        ("humas", "Maya Pratiwi"),
        ("warga", "Budi Santoso"),
        ("warga2", "Dewi Lestari"),
    ]

    # 1. Ketua membuat kegiatan baru
    k = login_actor(app, "ketua")
    r = post(k, "/kegiatan", {
        "nama": "Musyawarah Warga Terbuka",
        "jenis": "Rapat",
        "tanggal": "2026-12-01",
        "lokasi": "Balai Pertemuan",
    })
    assert r.status_code == 302
    kid = re.search(r"/kegiatan/(\d+)", r.headers["Location"]).group(1)

    # Dapatkan token presensi dari halaman kegiatan detail
    detail_html = k.get(f"/kegiatan/{kid}").data.decode()
    token = re.search(r"/presensi/([\w-]+)", detail_html).group(1)

    # 2. Verifikasi semua aktor non-admin bisa melihat menu Presensi QR, membuka halaman daftar & detail QR
    for username, nama_lengkap in aktor_roles:
        client = login_actor(app, username)

        # Cek halaman utama / (dashboard) memiliki link / menu Presensi QR
        dash = client.get("/").data.decode()
        assert "/kegiatan" in dash, f"{username} tidak memiliki menu Presensi QR di navigasi!"

        # Cek akses ke /kegiatan (daftar presensi)
        resp_kegiatan = client.get("/kegiatan")
        assert resp_kegiatan.status_code == 200, f"{username} tidak bisa membuka /kegiatan!"
        html_kegiatan = resp_kegiatan.data.decode()

        # Harus ada nama kegiatan, tombol Lihat QR, link QR & daftar hadir, dan SVG QR
        assert "Musyawarah Warga Terbuka" in html_kegiatan
        assert "Lihat QR" in html_kegiatan, f"{username} tidak melihat tombol 'Lihat QR'!"
        assert f"/kegiatan/{kid}" in html_kegiatan, f"{username} tidak melihat link detail QR!"
        assert "<svg" in html_kegiatan, f"{username} tidak memiliki kode QR SVG di tampilan!"

        # Cek akses ke /kegiatan/<kid> (halaman QR Code dan daftar hadir)
        resp_detail = client.get(f"/kegiatan/{kid}")
        assert resp_detail.status_code == 200, f"{username} tidak bisa membuka /kegiatan/{kid}!"
        html_detail = resp_detail.data.decode()
        assert "QR Presensi Kehadiran" in html_detail
        assert "<svg" in html_detail, f"{username} tidak melihat kode QR di halaman detail!"
        assert "Daftar hadir" in html_detail

        # Tombol toggle hanya untuk ketua/sekretaris/humas
        if username in ("ketua", "sekretaris", "humas"):
            assert f"/kegiatan/{kid}/toggle" in html_detail
        else:
            assert f"/kegiatan/{kid}/toggle" not in html_detail

    # 3. Presensi kehadiran oleh Warga (Budi Santoso) lewat URL QR
    w = login_actor(app, "warga")
    presensi_warga = w.get(f"/presensi/{token}")
    assert presensi_warga.status_code == 200
    assert "Ya, saya hadir" in presensi_warga.data.decode()
    post(w, f"/presensi/{token}")

    # 4. Presensi kehadiran oleh Bendahara (Agus Salim) lewat URL QR
    b = login_actor(app, "bendahara")
    presensi_bendahara = b.get(f"/presensi/{token}")
    assert presensi_bendahara.status_code == 200
    assert "Ya, saya hadir" in presensi_bendahara.data.decode()
    post(b, f"/presensi/{token}")

    # 5. Admin Sistem tidak memiliki akses presensi QR (menu tersembunyi, rute ditolak)
    a = login_actor(app, "admin")
    assert "/kegiatan" not in a.get("/").data.decode()
    assert a.get("/kegiatan").status_code == 403
    assert a.get(f"/kegiatan/{kid}").status_code == 403
    assert a.get(f"/presensi/{token}").status_code == 403

    # 6. Periksa daftar hadir dari sudut pandang warga, bendahara, dan ketua
    for actor in (w, b, k):
        det = actor.get(f"/kegiatan/{kid}").data.decode()
        assert "Budi Santoso" in det, "Kehadiran warga tidak tercatat di daftar hadir!"
        assert "Agus Salim" in det, "Kehadiran bendahara tidak tercatat di daftar hadir!"

    for actor in (w, b):
        assert "Kehadiran Anda sudah tercatat" in actor.get(f"/presensi/{token}").data.decode()
