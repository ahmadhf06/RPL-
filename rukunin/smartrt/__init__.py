"""Smart RT - Sistem Informasi Manajemen Lingkungan Digital (Flask + SQLite)."""
import os
import sqlite3

from flask import Flask, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from . import core, telegram_bot, ui
from .config import Config

ICONS = {
    "home": '<path d="M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
    "wallet": '<path d="M20 12V8H6a2 2 0 0 1 0-4h12v4"/><path d="M4 6v12a2 2 0 0 0 2 2h14v-4"/><path d="M18 12a2 2 0 0 0 0 4h4v-4z"/>',
    "receipt": '<path d="M4 2v20l3-2 3 2 3-2 3 2 3-2 1 1V2l-1 1-3-1-3 2-3-2-3 2z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "megaphone": '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "vote": '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "message": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "qr": '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v.01M14 20h3M20 17v4"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M10.85 12.15L19 4M18 5l3 3M15 8l3 3"/>',
    "cog": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "bell": '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "menu": '<path d="M3 12h18M3 6h18M3 18h18"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "dot": '<circle cx="12" cy="12" r="3"/>',
    "siren": '<path d="M12 2v2M4.93 4.93l1.41 1.41M19.07 4.93l-1.41 1.41M7 12a5 5 0 0 1 10 0v3H7v-3z"/><path d="M9 15v1a3 3 0 0 0 6 0v-1"/><line x1="12" y1="2" x2="12" y2="2"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "arrow_right": '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "trending_up": '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
    "coins": '<circle cx="9" cy="9" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18M7 6h4M9 6v6"/>',
    "clipboard": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M9 12h6M9 16h6"/>',
    "assembly": '<circle cx="12" cy="7" r="3"/><circle cx="5" cy="9" r="2.4"/><circle cx="19" cy="9" r="2.4"/><path d="M7 20v-2a5 5 0 0 1 10 0v2M1.5 19v-1.2a3.5 3.5 0 0 1 3.5-3.5M22.5 19v-1.2a3.5 3.5 0 0 0-3.5-3.5"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "chev_down": '<polyline points="6 9 12 15 18 9"/>',
    "chev_right": '<polyline points="9 18 15 12 9 6"/>',
    "close": '<path d="M18 6L6 18M6 6l12 12"/>',
    "pin": '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>',
    "cloud": '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "panel": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
    "rukun": '<path d="M3 10.5L12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5v-9z"/><circle cx="12" cy="11" r="2"/><path d="M8.5 18v-1.2a3.5 3.5 0 0 1 7 0V18"/><circle cx="6.5" cy="12" r="1.5"/><circle cx="17.5" cy="12" r="1.5"/>',
}
ICONS = {k: Markup(v) for k, v in ICONS.items()}

NON_ADMIN = ("ketua", "sekretaris", "bendahara", "humas", "warga")
# (label, endpoint, ikon, peran yang boleh melihat, awalan endpoint untuk menandai menu aktif)
# Urutan mengikuti rancangan: Dashboard, Data Warga, Surat, Keuangan, Kas, Musyawarah, Laporan, Alarm ... lalu menu tambahan.
NAV = [
    ("Dashboard", "main.dashboard", "home", core.ALL, "main.dashboard"),
    ("Data Warga", "warga.index", "users", ("ketua", "sekretaris", "bendahara"), "warga."),
    ("Surat & Administrasi", "surat.index", "file", ("warga", "sekretaris", "ketua"), "surat."),
    ("Keuangan RT", "keuangan.index", "wallet", ("ketua", "bendahara"), "keuangan."),
    ("Kas RT", "tagihan.index", "coins", ("ketua", "bendahara"), "tagihan.index"),
    ("Tagihan Saya", "tagihan.saya", "receipt", ("warga",), "tagihan.saya"),
    ("Voting", "komunitas.voting", "vote", NON_ADMIN, "komunitas.voting"),
    ("Transparansi Kas", "transparansi.transparansi", "coins", ("warga", "sekretaris", "humas"), "transparansi."),
    ("Laporan Lingkungan", "laporan.index", "clipboard", ("warga", "ketua", "sekretaris", "bendahara", "humas"), "laporan."),
    ("Alarm Darurat", "darurat.panel", "siren", NON_ADMIN, "darurat."),
    ("Pengumuman", "komunitas.pengumuman", "megaphone", core.ALL, "komunitas.pengumuman"),
    ("Jadwal Ronda", "komunitas.ronda", "shield", NON_ADMIN, "komunitas.ronda"),
    ("Aspirasi", "komunitas.aspirasi", "message", ("warga", "ketua", "humas"), "komunitas.aspirasi"),
    ("Presensi QR", "komunitas.kegiatan", "qr", NON_ADMIN, "komunitas.kegiatan"),
    ("Pendaftaran Warga", "pendaftaran.index", "user", ("ketua",), "pendaftaran."),
    ("Kelola Akun", "admin.akun", "key", ("admin",), "admin.akun"),
    ("Log Aktivitas", "admin.log_aktivitas", "list", ("admin",), "admin.log_aktivitas"),
]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    app.teardown_appcontext(core.close_db)
    app.before_request(core.csrf_protect)
    def avatar(u):
        """URL foto profil pengguna; memakai gambar bawaan bila belum mengunggah foto."""
        if u and u["foto"]:
            return url_for("main.avatar", name=u["foto"])
        return url_for("static", filename="img/avatar-default.svg")

    app.jinja_env.globals.update(csrf_token=core.csrf_token, STATUS=core.STATUS, ICONS=ICONS, avatar=avatar)
    app.jinja_env.filters.update(rupiah=core.rupiah, tgl=core.tgl, bulan=core.bulan_label, ago=core.ago)

    @app.context_processor
    def inject():
        u = core.current_user()
        unread = core.scalar("SELECT COUNT(*) FROM notifikasi WHERE user_id=? AND dibaca=0", (u["id"],)) if u else 0
        ep = request.endpoint or ""
        extra = {}
        if u:
            # Pengaturan: admin -> halaman pengaturan sistem; peran lain -> profil & akun
            pengaturan = ("admin.pengaturan", "admin.pengaturan") if u["role"] == "admin" else ("main.profil", "main.profil")
            extra = dict(panel=ui.panel_info(u), pengaturan=pengaturan)
        return dict(user=u, unread=unread, cfg=core.get_settings(), ROLES=core.ROLES,
                    nav=[n for n in NAV if u and u["role"] in n[3]], endpoint=ep, **extra)

    @app.after_request
    def secure_headers(r):
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["X-Frame-Options"] = "DENY"
        r.headers["Referrer-Policy"] = "same-origin"
        r.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.open-meteo.com; "
            "media-src 'self' blob:; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        if request.endpoint != "static":
            r.headers["Cache-Control"] = "no-store"
        return r

    @app.errorhandler(core.Invalid)
    def invalid(e):
        flash(str(e), "error")
        return redirect(core.safe_back())

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity(e):
        flash("Data tidak dapat disimpan: ada data kembar atau relasi yang tidak valid.", "error")
        return redirect(core.safe_back())

    def page_error(code, title, msg):
        return render_template("layout/error.html", code=code, title=title, msg=msg), code

    app.register_error_handler(400, lambda e: page_error(400, "Permintaan ditolak", getattr(e, "description", "")))
    app.register_error_handler(403, lambda e: page_error(403, "Akses ditolak", "Peran Anda tidak memiliki izin untuk halaman atau tindakan ini."))
    app.register_error_handler(404, lambda e: page_error(404, "Tidak ditemukan", "Halaman atau data yang Anda cari tidak tersedia."))
    app.register_error_handler(413, lambda e: page_error(413, "Berkas terlalu besar", "Ukuran unggahan terlalu besar (maksimal 10 MB per kiriman)."))
    app.register_error_handler(500, lambda e: page_error(500, "Kesalahan server", "Terjadi kesalahan. Coba lagi beberapa saat."))

    from .views import admin, darurat, keuangan, komunitas, laporan, main, pendaftaran, surat, warga
    for m in (main, admin, warga, surat, laporan, keuangan, komunitas, darurat, pendaftaran):
        app.register_blueprint(m.bp)
    app.register_blueprint(keuangan.tagihan_bp)
    app.register_blueprint(keuangan.transparan_bp)
    app.register_blueprint(surat.verif_bp)

    @app.cli.command("init-db")
    def init_db_cmd():
        """Buat tabel dan isi data awal (jika masih kosong)."""
        core.init_db()
        print("Database siap.")

    with app.app_context():
        core.init_db()
    telegram_bot.init_app(app)      # route webhook + bot Telegram di latar belakang (alarm darurat)
    return app
