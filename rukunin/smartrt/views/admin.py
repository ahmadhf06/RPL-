"""Admin: akun, hak akses (peran), konfigurasi sistem, log aktivitas."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..core import (ROLES, hash_pw, Invalid, choice, current_user, db, ensure_warga, ex, log, num, q, roles_required, scalar,
                    text, validate_password)

bp = Blueprint("admin", __name__, url_prefix="/admin")
PENGATURAN = [("nama_rt", "Nama RT / RW", 60), ("kelurahan", "Kelurahan", 80), ("kecamatan", "Kecamatan", 80),
              ("kota", "Kota/Kabupaten", 80), ("alamat_sekretariat", "Alamat sekretariat", 150),
              ("info_pembayaran", "Informasi pembayaran iuran", 300), ("nama_ttd", "Nama penanda tangan surat (kosong = nama akun Ketua RT yang menyetujui)", 80),
              ("telegram_chat_ids", "Telegram: Chat ID penerima & pengirim alarm darurat (pisahkan dengan koma; kirim /id ke bot untuk mengetahuinya)", 300)]


@bp.route("/akun")
@roles_required("admin")
def akun():
    rows = q("SELECT u.*, w.nama AS warga_nama FROM users u LEFT JOIN warga w ON w.user_id=u.id ORDER BY u.role, u.username")
    bebas = [(r["id"], r["nama"]) for r in q("SELECT id, nama FROM warga WHERE user_id IS NULL AND aktif=1 ORDER BY nama")]
    return render_template("admin/akun.html", rows=rows, bebas=bebas)


@bp.post("/akun")
@roles_required("admin")
def akun_add():
    username = (text("username", "Username", 30, pattern=r"[A-Za-z0-9_.]{3,30}") or "").lower()
    nama = text("nama", "Nama", 100)
    role = choice("role", "peran", ROLES)
    pw = request.form.get("password", "")
    validate_password(pw)
    if scalar("SELECT 1 FROM users WHERE username=?", (username,)):
        raise Invalid("Username sudah dipakai.")
    uid = ex("INSERT INTO users(username,password_hash,nama,role) VALUES(?,?,?,?)",
             (username, hash_pw(pw), nama, role))
    if role == "warga":                      # hubungkan ke data warga yang ada, atau buat baru
        wid = num("warga_id", "Data warga", 1, 10 ** 9, required=False)
        if wid and scalar("SELECT 1 FROM warga WHERE id=? AND user_id IS NULL", (wid,)):
            ex("UPDATE warga SET user_id=? WHERE id=?", (uid, wid))
        else:
            ensure_warga(uid, nama)
    log("akun_baru", f"{username} ({role})")
    flash(f"Akun {username} dibuat.", "ok")
    return redirect(url_for("admin.akun"))


@bp.post("/akun/<int:uid>")
@roles_required("admin")
def akun_edit(uid):
    u = q("SELECT * FROM users WHERE id=?", (uid,), one=True)
    if not u:
        raise Invalid("Akun tidak ditemukan.")
    nama = text("nama", "Nama", 100)
    role = choice("role", "peran", ROLES)
    aktif = 1 if request.form.get("aktif") else 0
    if uid == current_user()["id"] and (role != u["role"] or not aktif):
        raise Invalid("Anda tidak dapat mengubah peran atau menonaktifkan akun Anda sendiri.")
    if aktif and scalar("SELECT 1 FROM pendaftaran WHERE user_id=? AND status='menunggu'", (uid,)):
        raise Invalid("Akun ini masih menunggu verifikasi Ketua RT. Aktifkan lewat menu Pendaftaran Warga (Ketua RT).")
    pw = request.form.get("password", "")
    if pw:
        validate_password(pw)
        ex("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(pw), uid), commit=False)
    ex("UPDATE users SET nama=?, role=?, aktif=? WHERE id=?", (nama, role, aktif, uid), commit=False)
    db().commit()
    if role == "warga":
        ensure_warga(uid, nama)
    log("akun_ubah", f"{u['username']} -> {role}, aktif={aktif}{', reset password' if pw else ''}")
    flash("Akun diperbarui.", "ok")
    return redirect(url_for("admin.akun"))


@bp.route("/pengaturan", methods=["GET", "POST"])
@roles_required("admin")
def pengaturan():
    if request.method == "POST":
        vals = {k: text(k, label, mx, required=(k in ("nama_rt",))) or "" for k, label, mx in PENGATURAN}
        vals["iuran_bulanan"] = str(num("iuran_bulanan", "Iuran bulanan", 1000, 10 ** 8))
        for k, v in vals.items():
            ex("INSERT INTO settings(nama,nilai) VALUES(?,?) ON CONFLICT(nama) DO UPDATE SET nilai=excluded.nilai",
               (k, v), commit=False)
        db().commit()
        log("pengaturan_ubah")
        flash("Pengaturan disimpan.", "ok")
        return redirect(url_for("admin.pengaturan"))
    return render_template("admin/pengaturan.html", fields=PENGATURAN)


@bp.route("/log")
@roles_required("admin")
def log_aktivitas():
    rows = q("SELECT l.*, u.username FROM activity_log l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT 200")
    return render_template("admin/log.html", rows=rows)
