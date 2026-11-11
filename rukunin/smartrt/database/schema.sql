-- Skema database Smart RT (SQLite). Idempoten: aman dijalankan berulang.
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  nama TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','ketua','sekretaris','bendahara','humas','warga')),
  aktif INTEGER NOT NULL DEFAULT 1,
  last_login TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  foto TEXT,
  ttd_gambar TEXT
);
CREATE TABLE IF NOT EXISTS warga(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  nik TEXT UNIQUE, kk TEXT, nama TEXT NOT NULL, jk TEXT,
  tempat_lahir TEXT, tgl_lahir TEXT, alamat TEXT, telepon TEXT, pekerjaan TEXT,
  status_tinggal TEXT NOT NULL DEFAULT 'Tetap',
  aktif INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS settings(nama TEXT PRIMARY KEY, nilai TEXT);

CREATE TABLE IF NOT EXISTS surat(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  warga_id INTEGER NOT NULL REFERENCES warga(id),
  jenis TEXT NOT NULL, keperluan TEXT NOT NULL, keterangan TEXT,
  status TEXT NOT NULL DEFAULT 'diajukan'
    CHECK(status IN ('diajukan','menunggu_ketua','disetujui','selesai','ditolak')),
  nomor TEXT UNIQUE, draf TEXT, catatan TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  ttd_token TEXT UNIQUE, ttd_nama TEXT, ttd_pada TEXT, ttd_gambar TEXT
);
CREATE TABLE IF NOT EXISTS surat_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  surat_id INTEGER NOT NULL REFERENCES surat(id) ON DELETE CASCADE,
  status TEXT NOT NULL, oleh INTEGER REFERENCES users(id), catatan TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS laporan(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  judul TEXT NOT NULL, kategori TEXT NOT NULL, deskripsi TEXT NOT NULL,
  lokasi TEXT NOT NULL, lat REAL, lng REAL, foto TEXT,
  status TEXT NOT NULL DEFAULT 'baru' CHECK(status IN ('baru','diproses','selesai','ditolak')),
  pj_id INTEGER REFERENCES users(id), catatan TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tagihan(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  warga_id INTEGER NOT NULL REFERENCES warga(id),
  periode TEXT NOT NULL, jenis TEXT NOT NULL, nominal INTEGER NOT NULL CHECK(nominal>0),
  status TEXT NOT NULL DEFAULT 'belum_bayar'
    CHECK(status IN ('belum_bayar','menunggu_verifikasi','lunas','ditolak')),
  bukti TEXT, metode TEXT, tgl_bayar TEXT, verified_by INTEGER REFERENCES users(id), catatan TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(warga_id, periode, jenis)
);
CREATE TABLE IF NOT EXISTS transaksi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipe TEXT NOT NULL CHECK(tipe IN ('pemasukan','pengeluaran')),
  kategori TEXT NOT NULL, nominal INTEGER NOT NULL CHECK(nominal>0),
  keterangan TEXT, tanggal TEXT NOT NULL,
  tagihan_id INTEGER UNIQUE REFERENCES tagihan(id),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS ronda(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tanggal TEXT NOT NULL, warga_id INTEGER NOT NULL REFERENCES warga(id) ON DELETE CASCADE,
  pos TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pengumuman(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  judul TEXT NOT NULL, isi TEXT NOT NULL, penting INTEGER NOT NULL DEFAULT 0,
  author_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS aspirasi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  judul TEXT NOT NULL, isi TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'baru' CHECK(status IN ('baru','ditanggapi')),
  tanggapan TEXT, responded_by INTEGER REFERENCES users(id), responded_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS voting(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  judul TEXT NOT NULL, deskripsi TEXT, berakhir TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'aktif' CHECK(status IN ('aktif','ditutup')),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS voting_opsi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voting_id INTEGER NOT NULL REFERENCES voting(id) ON DELETE CASCADE, teks TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voting_suara(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voting_id INTEGER NOT NULL REFERENCES voting(id) ON DELETE CASCADE,
  opsi_id INTEGER NOT NULL REFERENCES voting_opsi(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(voting_id, user_id)                      -- 1 akun = 1 suara
);
CREATE TABLE IF NOT EXISTS kegiatan(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nama TEXT NOT NULL, jenis TEXT NOT NULL, tanggal TEXT NOT NULL, lokasi TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE, aktif INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS presensi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kegiatan_id INTEGER NOT NULL REFERENCES kegiatan(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id),
  waktu TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(kegiatan_id, user_id)
);
CREATE TABLE IF NOT EXISTS notifikasi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  judul TEXT NOT NULL, pesan TEXT, link TEXT, dibaca INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_notif ON notifikasi(user_id, dibaca);
CREATE TABLE IF NOT EXISTS activity_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, aksi TEXT NOT NULL, detail TEXT, ip TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Dynamic Voice Emergency Alert System
CREATE TABLE IF NOT EXISTS alarm_darurat(
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  jenis            TEXT    NOT NULL DEFAULT 'Darurat',
  pesan            TEXT,
  rekaman_file     TEXT,                              -- nama file rekaman warga (sementara)
  status           TEXT    NOT NULL DEFAULT 'aktif'
                     CHECK(status IN ('aktif','selesai')),
  diaktifkan_oleh  INTEGER REFERENCES users(id),
  diaktifkan_pada  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
  dihentikan_oleh  INTEGER REFERENCES users(id),
  dihentikan_pada  TEXT
);
CREATE INDEX IF NOT EXISTS idx_alarm_status ON alarm_darurat(status);

-- Pendaftaran akun warga mandiri: data diri + dokumen masuk ke Ketua RT untuk diverifikasi.
-- Akun dibuat nonaktif (users.aktif=0) sampai Ketua RT menyetujui; data warga baru dibuat saat disetujui.
CREATE TABLE IF NOT EXISTS pendaftaran(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  username TEXT NOT NULL,
  nik TEXT NOT NULL, kk TEXT, nama TEXT NOT NULL, jk TEXT NOT NULL,
  tempat_lahir TEXT, tgl_lahir TEXT, alamat TEXT NOT NULL, telepon TEXT, pekerjaan TEXT,
  status_tinggal TEXT NOT NULL DEFAULT 'Tetap',
  foto_ktp TEXT NOT NULL, foto_kk TEXT,
  status TEXT NOT NULL DEFAULT 'menunggu' CHECK(status IN ('menunggu','disetujui','ditolak')),
  catatan TEXT,
  diproses_oleh INTEGER REFERENCES users(id), diproses_pada TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_pendaftaran_status ON pendaftaran(status);
