"""Data awal: 7 akun uji (satu per peran, warga dua) + contoh data nyata di database."""
import secrets
from datetime import date, timedelta

from ..core import hash_pw as h

AKUN = [  # username, password, nama, peran
    ("admin", "Admin#2026", "Admin Sistem", "admin"),
    ("ketua", "Ketua#2026", "Hendra Wijaya", "ketua"),
    ("sekretaris", "Sekre#2026", "Siti Rahma", "sekretaris"),
    ("bendahara", "Bendahara#2026", "Agus Salim", "bendahara"),
    ("humas", "Humas#2026", "Maya Pratiwi", "humas"),
    ("warga", "Warga#2026", "Budi Santoso", "warga"),
    ("warga2", "Warga#2026", "Dewi Lestari", "warga"),
]
WARGA_LAIN = ["Ahmad Fauzi", "Rina Marlina", "Joko Susilo", "Sri Wahyuni"]


def seed(con):
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    ids = {}
    for u, pw, nama, role in AKUN:
        ids[u] = con.execute("INSERT INTO users(username,password_hash,nama,role) VALUES(?,?,?,?)",
                             (u, h(pw), nama, role)).lastrowid
    n = 0
    wid = {}
    for u, _, nama, role in AKUN:
        if role == "warga":
            n += 1
            wid[u] = con.execute(
                "INSERT INTO warga(user_id,nik,kk,nama,jk,tempat_lahir,tgl_lahir,alamat,telepon,pekerjaan)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ids[u], f"320101010190000{n}", f"320101010100000{n}", nama, "L" if u == "warga" else "P",
                 "Bekasi", "1990-01-0%d" % n, f"Jl. Melati No. {n}", f"08123456780{n}", "Karyawan Swasta")).lastrowid
    for nama in WARGA_LAIN:
        n += 1
        wid[nama] = con.execute(
            "INSERT INTO warga(nik,kk,nama,jk,tempat_lahir,tgl_lahir,alamat,telepon,pekerjaan)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (f"320101010190000{n}", f"320101010100000{n}", nama, "L", "Bekasi", "1985-05-05",
             f"Jl. Melati No. {n}", f"08123456780{n}", "Wiraswasta")).lastrowid
    for k, v in {"nama_rt": "RT 03 / RW 05", "kelurahan": "Kelurahan Contoh", "kecamatan": "Kecamatan Contoh",
                 "kota": "Kota Bekasi", "alamat_sekretariat": "Pos RT 03, Jl. Melati", "iuran_bulanan": "50000",
                 "info_pembayaran": "Transfer ke BCA 1234567890 a.n. Bendahara RT 03, lalu unggah bukti di sini.",
                 "nama_ttd": ""}.items():
        con.execute("INSERT INTO settings VALUES(?,?)", (k, v))
    today = date.today()
    con.execute("INSERT INTO pengumuman(judul,isi,penting,author_id) VALUES(?,?,?,?)",
                ("Selamat datang di Smart RT", "Aplikasi ini kini dipakai untuk surat, laporan, iuran, dan voting warga.",
                 1, ids["ketua"]))
    con.execute("INSERT INTO pengumuman(judul,isi,author_id) VALUES(?,?,?)",
                ("Kerja bakti Minggu pagi", "Seluruh warga diharapkan hadir pukul 07.00 membawa peralatan kebersihan.",
                 ids["ketua"]))
    v = con.execute("INSERT INTO voting(judul,deskripsi,berakhir,created_by) VALUES(?,?,?,?)",
                    ("Jadwal kerja bakti bulanan", "Pilih hari yang paling cocok untuk kerja bakti rutin.",
                     (today + timedelta(days=14)).isoformat(), ids["ketua"])).lastrowid
    for t in ("Minggu pagi", "Sabtu sore", "Sabtu pagi"):
        con.execute("INSERT INTO voting_opsi(voting_id,teks) VALUES(?,?)", (v, t))
    con.execute("INSERT INTO kegiatan(nama,jenis,tanggal,lokasi,token,created_by) VALUES(?,?,?,?,?,?)",
                ("Rapat Warga Bulanan", "Rapat", (today + timedelta(days=3)).isoformat(), "Balai Warga",
                 secrets.token_urlsafe(9), ids["ketua"]))
    periode = today.strftime("%Y-%m")
    for key, w in wid.items():
        t = con.execute("INSERT INTO tagihan(warga_id,periode,jenis,nominal) VALUES(?,?,?,?)",
                        (w, periode, "Iuran Bulanan", 50000)).lastrowid
        if key == "Ahmad Fauzi":
            con.execute("UPDATE tagihan SET status='lunas',metode='Tunai',tgl_bayar=?,verified_by=? WHERE id=?",
                        (today.isoformat(), ids["bendahara"], t))
            con.execute("INSERT INTO transaksi(tipe,kategori,nominal,keterangan,tanggal,tagihan_id,created_by)"
                        " VALUES('pemasukan','Iuran Warga',50000,?,?,?,?)",
                        (f"Iuran Bulanan {periode} - {key}", today.isoformat(), t, ids["bendahara"]))
    con.execute("INSERT INTO transaksi(tipe,kategori,nominal,keterangan,tanggal,created_by) VALUES(?,?,?,?,?,?)",
                ("pemasukan", "Saldo Awal", 1500000, "Saldo kas awal", (today - timedelta(days=30)).isoformat(),
                 ids["bendahara"]))
    con.execute("INSERT INTO transaksi(tipe,kategori,nominal,keterangan,tanggal,created_by) VALUES(?,?,?,?,?,?)",
                ("pengeluaran", "Kebersihan", 250000, "Upah petugas kebersihan", (today - timedelta(days=5)).isoformat(),
                 ids["bendahara"]))
    for i, key in enumerate(["warga", "Ahmad Fauzi", "Joko Susilo", "warga2"]):
        con.execute("INSERT INTO ronda(tanggal,warga_id,pos) VALUES(?,?,?)",
                    ((today + timedelta(days=1 + i // 2)).isoformat(), wid[key], "Pos Ronda Utama"))
