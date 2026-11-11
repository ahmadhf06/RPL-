# RUKUNIN (Smart RT) — Sistem Informasi Manajemen Lingkungan Digital

Flask + SQLite, satu database terpusat. Semua data (surat, laporan, tagihan, voting, presensi, notifikasi) tersimpan di database;
tidak ada data statis pengganti. Tampilan Modern Glassmorphism + ilustrasi lingkungan perumahan: sidebar hijau tua di kiri, dashboard di tengah, panel profil di kanan; responsif (HP/tablet/laptop).

## Instalasi & menjalankan
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                      # buka http://localhost:5000
```
Database `instance/smartrt.db` dibuat otomatis beserta data awal. Reset: hapus folder `instance/` lalu jalankan ulang.

**Akses dari HP/tablet:** jalankan di satu komputer, cari IP-nya (mis. `192.168.1.10`), lalu buka `http://192.168.1.10:5000`
dari perangkat lain di WiFi yang sama. Agar QR presensi memakai alamat itu secara tetap: `PUBLIC_BASE_URL=http://192.168.1.10:5000`.

## Tampilan (redesign RUKUNIN)
Konsep **Modern Glassmorphism + Neighborhood Illustration Dashboard**. Backend, database, dan semua fitur lama tidak berubah; yang berubah hanya lapisan tampilan.

| Bagian | Isi |
|---|---|
| Sidebar kiri | Deep Forest `#283618`, logo, menu outline, menu aktif Olive `#606c38` (meluncur halus saat pindah menu), Pengaturan & Keluar, ilustrasi rumah di bawah |
| Konten tengah | Pencarian, sapaan, 4 kartu statistik, grafik keuangan, jadwal kegiatan, aktivitas terbaru, laporan lingkungan terbaru |
| Panel kanan | Avatar, jabatan, **Edit Profil** (popup kaca), RT & kelurahan, aksi cepat, cuaca & lokasi, quote, ilustrasi gapura RT + status lingkungan |

* **Palet:** `#283618` · `#606c38` · `#dda15e` · `#fefae0` (dasar kaca `rgba(254,250,224,.15)`, blur 15px, sudut 16–20px).
* **Font:** Plus Jakarta Sans (judul, angka, navigasi) + Inter (isi, tabel, formulir) dari Google Fonts; ada cadangan font sistem bila offline.
* **Animasi (250–350 ms):** fade + slide up antarhalaman, kartu muncul bertahap, hover, popup kaca, skeleton loading. Otomatis dimatikan bila sistem memilih "kurangi gerakan".
* **Responsif:** ≤1200px sidebar jadi rel ikon dan panel kanan jadi laci (tombol di topbar); ≤900px sidebar jadi laci + navigasi bawah.
* **Panel kanan di desktop** tampil otomatis di Dashboard dan bisa ditampilkan/disembunyikan di halaman lain (tombol di topbar; pilihan diingat browser).
* **Kartu statistik per peran:** Ketua/Bendahara melihat Total Warga, Kas RT, Iuran Terbayar, dan Pengajuan Surat (Bendahara: Menunggu Verifikasi); peran lain melihat angka yang relevan dengan haknya (RBAC tidak diubah).

### Mengganti gambar lingkungan
Semua ilustrasi ada di `smartrt/static/img/` — cukup timpa file dengan nama yang sama (SVG/PNG, rasio sama):
`lingkungan-hero.svg` (latar dashboard, 1600×380) · `sidebar-rumah.svg` · `panel-gapura.svg` (rasio 400:460; tulisan RT diletakkan otomatis di plakat) · `balai-musyawarah.svg` · `avatar-default.svg` · `logo-rukunin.svg`.

### Cuaca di panel kanan
Memakai Open-Meteo (tanpa kunci API, butuh internet). Koordinat bawaan Jakarta; ubah lewat variabel lingkungan `WEATHER_LAT` / `WEATHER_LNG`
atau isi pengaturan `lat` dan `lng` di tabel `settings`. Tanpa internet kartu menampilkan "Cuaca belum tersedia".

## Login & akun
Login memakai form biasa (username + kata sandi); tidak ada lagi tombol/akun uji yang mengisi form otomatis.
Akun awal di bawah ini hanya dibuat di database **baru** (untuk pengembangan). **Ganti semua kata sandinya sebelum dipakai nyata**
(Kelola Akun, atau Profil → Ganti kata sandi).

| Peran | Username | Kata sandi awal |
|---|---|---|
| Admin | `admin` | `Admin#2026` |
| Ketua RT | `ketua` | `Ketua#2026` |
| Sekretaris | `sekretaris` | `Sekre#2026` |
| Bendahara | `bendahara` | `Bendahara#2026` |
| Humas | `humas` | `Humas#2026` |
| Warga | `warga` / `warga2` | `Warga#2026` |

**Database lama (`instance/smartrt.db`) dimigrasi otomatis** saat aplikasi dijalankan: tabel `users` dibangun ulang agar menerima peran
`humas` (data, id, dan kata sandi tetap), dan tabel `pendaftaran` ditambahkan. Akun Humas tidak dibuat otomatis di database lama;
buat lewat **Admin → Kelola Akun → Peran: Humas**.

## Pendaftaran warga mandiri
Alur: `/daftar` (publik) → akun dibuat **nonaktif** → data diri + KTP/KK masuk ke antrean **Ketua RT** (menu *Pendaftaran Warga*, notifikasi lonceng,
kartu di dashboard) → Ketua RT **menyetujui** (akun aktif, data warga dibuat; bila NIK sudah pernah didata tanpa akun, dihubungkan ke data itu, tidak dobel)
atau **menolak** dengan alasan (tampil ke pendaftar saat mencoba masuk; ia boleh mendaftar ulang dengan username yang sama).

* Peran akun hasil pendaftaran selalu **Warga**; peran/status dari formulir tidak dipercaya. Admin tidak bisa mengaktifkan akun yang masih menunggu verifikasi.
* KTP/KK hanya dapat dibuka **Ketua RT** (lewat `/media/…` yang memeriksa hak akses), JPG/PNG/WEBP maks. 4 MB per berkas, isi berkas diperiksa.
* Pembatasan per IP: 30 percobaan kirim formulir/jam dan 5 pendaftaran berhasil/jam. Pesan duplikat NIK/username tidak merinci pemiliknya.
* Matikan pendaftaran publik dengan variabel lingkungan `ALLOW_REGISTRATION=0` (tautan "Daftar" di halaman masuk ikut hilang).

## Bot Telegram (alarm terdengar di luar web)
Alarm darurat tersambung ke bot Telegram, dua arah:

- **Web → Telegram:** alarm yang dinyalakan/dimatikan di web dikirim ke semua chat terdaftar, sehingga HP berbunyi walau tidak sedang membuka web.
  Alarm masuk sebagai satu pesan audio: sirene MP3 yang bisa langsung diputar + keterangan alarm (nada dering mengikuti pengaturan notifikasi Telegram di HP).
- **Telegram → Web:** pesan berisi kata `darurat` atau `bahaya` dari chat terdaftar menyalakan sirene di semua browser yang membuka RUKUNIN
  (tercatat di Riwayat Alarm sebagai "Bot Telegram"). Ketua RT mematikannya dari web seperti biasa.

**Pengaturan (sekali saja):**
1. Simpan token dari @BotFather di berkas `instance/telegram_token.txt` (satu baris, berkas ini tidak ikut Git) atau di variabel lingkungan `TELEGRAM_BOT_TOKEN`.
2. Jalankan `python run.py`. Di konsol muncul `[Telegram] Bot terhubung: @namabot`.
3. Kirim `/id` ke bot (atau ke grup RT yang berisi bot). Bot membalas Chat ID.
4. Admin memasukkan Chat ID itu di **Pengaturan Sistem → Telegram** (beberapa ID dipisah koma; ID grup berawalan minus), atau menuliskannya di `CHAT_ID_BAWAAN`
   pada `smartrt/telegram_bot.py`, atau lewat `TELEGRAM_CHAT_IDS`.
5. Buka **Alarm Darurat → Bot Telegram → Kirim pesan tes** untuk memastikan pesan sampai.

Hanya chat yang Chat ID-nya terdaftar yang bisa menyalakan alarm; pesan dari orang asing diabaikan. Perintah bot: `/id`, `/status`.

**Mode penerimaan pesan** (`TELEGRAM_MODE`): `polling` (bawaan, tidak perlu ngrok/alamat publik), `webhook` (isi `TELEGRAM_WEBHOOK_URL` dengan alamat https publik;
webhook didaftarkan otomatis), atau `off`. Dengan gunicorn gunakan `--workers 1` (mode polling) atau mode webhook.
Sirene bawaan adalah `static/audio/alarm.mp3`; Ketua RT/admin tetap bisa menggantinya lewat panel Alarm Darurat.
Suara di browser hanya bisa menyala setelah halaman RUKUNIN pernah diketuk/diklik sekali (aturan autoplay browser).

## Alarm berbunyi otomatis di HP (ntfy)
Telegram tidak bisa memutar sirene otomatis di HP (yang berbunyi hanya nada notifikasi, sirene harus diketuk). Untuk bunyi yang muncul sendiri,
alarm juga dikirim sebagai notifikasi **prioritas tertinggi** lewat aplikasi gratis [ntfy](https://ntfy.sh) (Android/iOS), tanpa akun.

1. Jalankan Rukunin. Buka **Alarm Darurat → Alarm Berbunyi Otomatis di HP** (Ketua RT/admin): di sana tertulis nama topik acak.
2. Di HP warga: pasang ntfy, ketuk **+**, isi topik tersebut, berlangganan.
3. Android: di ntfy aktifkan *Keep alerting for highest priority* (suara berulang), lalu ketuk lama notifikasi ntfy, pilih kanal prioritas tertinggi,
   pasang nada sirene dan izinkan menembus Jangan Ganggu. iPhone: izinkan ntfy pada mode Fokus; pengulangan suara tidak bisa diandalkan.
4. Tekan **Kirim notifikasi tes** untuk memastikan.

Nama topik bersifat rahasia seperti kata sandi (disimpan di `instance/ntfy_topic.txt`); pesan alarm lewat server ntfy.sh. Matikan dengan `NTFY_MODE=off`;
ganti server/topik dengan `NTFY_SERVER` / `NTFY_TOPIC`. Alarm dari web maupun dari Telegram sama-sama dikirim ke ntfy.

## Hak akses
| Fitur | Admin | Ketua | Sekretaris | Bendahara | Humas | Warga |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Kelola akun, peran, pengaturan, log | ✔ | | | | | |
| Verifikasi pendaftaran warga (data + KTP/KK) | | ✔ | | | | daftar sendiri |
| Data warga | | kelola | lihat | lihat | — | profil sendiri |
| Surat | | setujui/tolak | periksa, draf, nomor, arsip | | — | ajukan, lihat sendiri |
| Laporan lingkungan | | pantau, tunjuk PJ | PJ bila ditunjuk | PJ bila ditunjuk | PJ bila ditunjuk | buat, lihat sendiri |
| Kas, tagihan, verifikasi | | lihat | | kelola | — | tagihan sendiri + unggah bukti |
| Pengumuman | | buat/hapus semua | lihat | lihat | buat, hapus miliknya | lihat |
| Ronda | | kelola | kelola | lihat | lihat | lihat |
| Aspirasi | | lihat & tanggapi | | | lihat & tanggapi | kirim, lihat sendiri |
| Voting | | buat/tutup, lihat hasil | lihat | lihat | lihat (termasuk hasil) | memilih (1 akun = 1 suara) |
| Kegiatan & presensi QR | — (tidak ada akses) | buat kegiatan | buat kegiatan | hadir | buat kegiatan | hadir (pindai QR) |
| Alarm darurat | | nyalakan & matikan | nyalakan | nyalakan | nyalakan | nyalakan |

Alur surat: **Warga → Sekretaris (periksa, draf, nomor) → Ketua RT (setujui) → Sekretaris (arsip) → Selesai**.
Sekretaris tidak memiliki aksi "setujui" sama sekali (ditegakkan di server, bukan hanya disembunyikan di UI).

## Struktur
```
Smart-RT-Flask/
├── run.py                  titik masuk (python run.py), membuka browser otomatis
├── jalankan.bat / .sh      jalan pintas: siapkan .venv, pasang modul, jalankan run.py
├── requirements.txt        daftar modul Python
├── README.md
├── instance/               DATA yang dibuat saat aplikasi jalan (database, unggahan, kunci); aman dihapus untuk reset
├── tests/
│   ├── test_smoke.py       uji end-to-end seluruh alur & RBAC  ->  python -m pytest -q
│   ├── test_humas_daftar.py uji peran Humas, pendaftaran warga, login, migrasi database lama
│   ├── test_telegram.py    uji bot Telegram <-> alarm darurat (tanpa internet)
│   └── test_ntfy.py        uji notifikasi alarm yang berbunyi otomatis di HP (ntfy)
└── smartrt/                SELURUH kode aplikasi
    ├── __init__.py         app factory, header keamanan, menu per peran
    ├── config.py           pengaturan aplikasi
    ├── core.py             database, RBAC, CSRF, validasi, unggah aman, notifikasi
    ├── telegram_bot.py     bot Telegram: alarm web -> HP warga, pesan "darurat" Telegram -> alarm web
    ├── ntfy_push.py        notifikasi prioritas tertinggi ke HP lewat aplikasi ntfy (berbunyi otomatis)
    ├── database/
    │   ├── schema.sql      skema database (20 tabel)
    │   └── seed.py         akun & data awal
    ├── views/              (SEMUA route Python, satu file per fitur)
    │   ├── main.py         login, dashboard, notifikasi, profil, API JSON
    │   ├── admin.py        kelola akun, pengaturan, log aktivitas
    │   ├── warga.py        data warga
    │   ├── pendaftaran.py  pendaftaran warga mandiri (/daftar) + verifikasi Ketua RT (/pendaftaran)
    │   ├── surat.py        surat & administrasi
    │   ├── laporan.py      laporan lingkungan
    │   ├── keuangan.py     kas RT & tagihan
    │   ├── komunitas.py    pengumuman, ronda, aspirasi, voting, presensi QR
    │   └── darurat.py      alarm darurat
    ├── templates/          (SEMUA halaman HTML, nama folder = nama file di views/)
    │   ├── layout/         base.html (kerangka), macros.html (komponen), error.html
    │   ├── main/           login, daftar, daftar_terkirim, dashboard, notifikasi, profil
    │   ├── admin/          akun, pengaturan, log
    │   ├── warga/          list, form
    │   ├── pendaftaran/    list, detail (khusus Ketua RT)
    │   ├── surat/          list, form, detail, cetak
    │   ├── laporan/        list, form, detail
    │   ├── keuangan/       index, tagihan, tagihan_saya
    │   ├── komunitas/      pengumuman, ronda, aspirasi, voting, kegiatan, kegiatan_detail, presensi
    │   └── darurat/        index
    ├── ui.py               data tampilan dashboard & panel (aksi cepat, aktivitas, grafik kas)
    └── static/
        ├── css/            gaya tampilan, dipecah per bagian (urutan muat: lihat templates/layout/styles.html)
        │   ├── base.css        variabel warna, reset, kerangka halaman
        │   ├── sidebar.css     sidebar kiri dan indikator menu aktif
        │   ├── topbar.css      topbar: pencarian, chip pengguna, lonceng
        │   ├── dashboard.css   sapaan, kartu kaca (.card), statistik, grafik, jadwal, daftar aktivitas
        │   ├── panel.css       panel profil kanan (avatar, aksi cepat, cuaca, ilustrasi gapura)
        │   ├── components.css  tombol, formulir, tabel
        │   ├── darurat.css     panel alarm darurat
        │   ├── login.css       halaman login
        │   ├── notifikasi.css  toast notifikasi dan dropdown lonceng
        │   ├── motion.css      animasi (fade + slide up, stagger) dan skeleton loading
        │   └── responsive.css  tampilan HP/tablet (HARUS dimuat paling akhir)
        ├── img/            ILUSTRASI lingkungan & logo (mudah diganti)
        ├── audio/alarm.mp3 sirene bawaan (dipakai bila belum ada sirene yang diunggah)
        └── js/
            ├── app.js      skrip umum (sidebar, notifikasi, pencarian)
            └── darurat.js  skrip halaman alarm darurat (rekam suara, sirene, VN)
```

**Cara mencari file:** fitur "surat" -> `views/surat.py` (logika) + `templates/surat/` (tampilan).
Tampilan umum (menu, kerangka halaman) -> `templates/layout/`.
Mengubah warna/gaya -> cari bagiannya di `static/css/` (mis. sidebar -> `sidebar.css`, tombol & tabel -> `components.css`).
Menambah file CSS baru -> daftarkan di `templates/layout/styles.html` (urutan penting; `responsive.css` tetap paling akhir).

## API JSON (untuk sinkronisasi antarperangkat)
`GET /api/notifikasi`, `GET /api/stats` (angka dashboard sesuai peran). Dipoll browser tiap 20 detik; 401 bila belum login.

## Keamanan
RBAC di setiap route · hash kata sandi (scrypt, Werkzeug) · token CSRF pada semua POST · cookie sesi HttpOnly + SameSite=Lax,
sesi 4 jam, sesi diganti saat login · pembatasan 5x gagal login/5 menit · query berparameter (anti SQL injection) · Jinja autoescape (anti XSS) ·
unggahan diperiksa isi berkasnya, dinamai acak, disajikan lewat route yang memeriksa hak akses · CSP, X-Frame-Options, nosniff · ekspor CSV anti formula-injection.

## Produksi
Set `SECRET_KEY`, `COOKIE_SECURE=1` (HTTPS), ganti semua kata sandi awal, dan jalankan dengan
`gunicorn "smartrt:create_app()"` di belakang HTTPS (nginx/Caddy). Untuk MySQL, ganti lapisan `core.db()` ke konektor MySQL
(SQL yang dipakai standar; `datetime('now')`/`INSERT OR IGNORE` perlu disesuaikan).
