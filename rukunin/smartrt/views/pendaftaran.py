"""Pendaftaran akun warga mandiri.

Alur:  Calon warga mengisi data diri + unggah KTP/KK di /daftar
       -> akun dibuat NONAKTIF dan data masuk ke antrean Ketua RT (/pendaftaran)
       -> Ketua RT memeriksa lalu menyetujui (akun aktif, data warga dibuat/dihubungkan) atau menolak (dengan alasan).
Hanya Ketua RT yang dapat melihat data & dokumen pendaftar.
"""
import os

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, url_for)

from ..core import (Invalid, choice, current_user, datestr, db, hash_pw, log, notify, q, rate_limited, roles_required,
                    save_image, scalar, text, users_by_role, validate_password)

bp = Blueprint("pendaftaran", __name__)

STATUS_DAFTAR = {"menunggu": ("Menunggu verifikasi", "amber"), "disetujui": ("Disetujui", "emerald"),
                 "ditolak": ("Ditolak", "red")}
MAKS_COBA_PER_JAM = 30           # percobaan kirim formulir per alamat IP (menahan penebakan username/NIK)
MAKS_DAFTAR_PER_JAM = 5          # pendaftaran BERHASIL per alamat IP, supaya antrean Ketua RT tidak dibanjiri
MAKS_MB_DOKUMEN = 4


def _hapus_berkas(*names):
    for n in names:
        if n:
            try:
                os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], n))
            except OSError:
                pass


# ---------------------------------------------------------------- sisi calon warga (publik)
@bp.route("/daftar", methods=["GET", "POST"])
def daftar():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if not current_app.config["ALLOW_REGISTRATION"]:
        flash("Pendaftaran akun baru sedang ditutup. Hubungi Ketua RT.", "error")
        return redirect(url_for("main.login"))
    if request.method == "POST":
        ip = request.remote_addr
        if (rate_limited(("daftar-coba", ip), MAKS_COBA_PER_JAM)
                or rate_limited(("daftar-ok", ip), MAKS_DAFTAR_PER_JAM, record=False)):
            flash("Terlalu banyak percobaan pendaftaran dari perangkat ini. Coba lagi dalam 1 jam.", "error")
            return render_template("main/daftar.html", v=request.form), 429
        try:
            _proses_daftar()
        except Invalid as e:                         # tampilkan ulang formulir beserta isian (kecuali kata sandi & berkas)
            flash(str(e), "error")
            return render_template("main/daftar.html", v=request.form), 400
        rate_limited(("daftar-ok", ip), MAKS_DAFTAR_PER_JAM)      # catat pendaftaran yang berhasil
        return redirect(url_for("pendaftaran.terkirim"))
    return render_template("main/daftar.html", v={})


def _proses_daftar():
    username = (text("username", "Username", 30, pattern=r"[A-Za-z0-9_.]{3,30}") or "").lower()
    pw = request.form.get("password", "")
    if pw != request.form.get("konfirmasi", ""):
        raise Invalid("Konfirmasi kata sandi tidak cocok.")
    validate_password(pw)
    d = dict(
        nama=text("nama", "Nama lengkap", 100),
        nik=text("nik", "NIK", 16, pattern=r"\d{16}"),
        kk=text("kk", "No. KK", 16, required=False, pattern=r"\d{16}"),
        jk=choice("jk", "jenis kelamin", ("L", "P")),
        tempat_lahir=text("tempat_lahir", "Tempat lahir", 60),
        tgl_lahir=datestr("tgl_lahir", "lahir"),
        alamat=text("alamat", "Alamat", 150),
        telepon=text("telepon", "Telepon", 20, pattern=r"[0-9+\- ]{8,20}"),
        pekerjaan=text("pekerjaan", "Pekerjaan", 60, required=False),
        status_tinggal=choice("status_tinggal", "status tinggal", ("Tetap", "Kontrak", "Kos")))

    # Pesan sengaja tidak merinci siapa pemilik NIK/username (hindari membocorkan data warga).
    if (scalar("SELECT 1 FROM warga WHERE nik=? AND user_id IS NOT NULL", (d["nik"],))
            or scalar("SELECT 1 FROM pendaftaran WHERE nik=? AND status='menunggu'", (d["nik"],))):
        raise Invalid("NIK ini tidak dapat didaftarkan karena sudah terdaftar atau sedang diverifikasi. Hubungi Ketua RT.")

    lama = q("SELECT * FROM users WHERE username=?", (username,), one=True)
    if lama:
        # Username dari pendaftaran yang DITOLAK (akun tidak pernah aktif) boleh dipakai lagi untuk mendaftar ulang.
        bekas_tolak = (not lama["aktif"] and lama["role"] == "warga"
                       and scalar("SELECT 1 FROM pendaftaran WHERE user_id=? AND status='ditolak'", (lama["id"],))
                       and not scalar("SELECT 1 FROM pendaftaran WHERE user_id=? AND status<>'ditolak'", (lama["id"],))
                       and not scalar("SELECT 1 FROM warga WHERE user_id=?", (lama["id"],)))
        if not bekas_tolak:
            raise Invalid("Username sudah dipakai. Pilih username lain.")
        db().execute("DELETE FROM users WHERE id=?", (lama["id"],))   # baris pendaftaran lama tetap ada sebagai arsip

    ktp = kk = None
    try:
        ktp = save_image("foto_ktp", required=True, label="Foto KTP", max_mb=MAKS_MB_DOKUMEN)
        kk = save_image("foto_kk", label="Foto Kartu Keluarga", max_mb=MAKS_MB_DOKUMEN)
        uid = db().execute("INSERT INTO users(username,password_hash,nama,role,aktif) VALUES(?,?,?,'warga',0)",
                           (username, hash_pw(pw), d["nama"])).lastrowid
        cols = list(d)
        pid = db().execute(
            f"INSERT INTO pendaftaran(user_id,username,{','.join(cols)},foto_ktp,foto_kk) VALUES(?,?,{','.join('?' * len(cols))},?,?)",
            [uid, username, *d.values(), ktp, kk]).lastrowid
        db().commit()
    except Exception:
        db().rollback()
        _hapus_berkas(ktp, kk)                      # jangan tinggalkan berkas yatim bila pendaftaran gagal
        raise
    log("daftar_baru", f"{username} #{pid}")
    notify(users_by_role("ketua"), "Pendaftaran warga baru", f"{d['nama']} menunggu verifikasi Anda.",
           url_for("pendaftaran.detail", pid=pid))


@bp.get("/daftar/terkirim")
def terkirim():
    return render_template("main/daftar_terkirim.html")


# ---------------------------------------------------------------- sisi Ketua RT
@bp.route("/pendaftaran")
@roles_required("ketua")
def index():
    status = request.args.get("status", "menunggu")
    if status not in STATUS_DAFTAR and status != "semua":
        status = "menunggu"
    where, args = ("", ()) if status == "semua" else ("WHERE p.status=?", (status,))
    rows = q("SELECT p.*, u.nama AS pemroses FROM pendaftaran p LEFT JOIN users u ON u.id=p.diproses_oleh "
             f"{where} ORDER BY (p.status='menunggu') DESC, p.id DESC LIMIT 300", args)
    hitung = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM pendaftaran GROUP BY status")}
    return render_template("pendaftaran/list.html", rows=rows, status=status, hitung=hitung, STATUS_DAFTAR=STATUS_DAFTAR)


def _get(pid):
    p = q("SELECT p.*, u.nama AS pemroses FROM pendaftaran p LEFT JOIN users u ON u.id=p.diproses_oleh WHERE p.id=?",
          (pid,), one=True)
    if not p:
        abort(404)
    return p


@bp.route("/pendaftaran/<int:pid>")
@roles_required("ketua")
def detail(pid):
    p = _get(pid)
    # Bila Ketua RT sudah pernah mendata warga ini (tanpa akun), persetujuan akan menghubungkannya, bukan menggandakan.
    ada = q("SELECT id, nama, user_id FROM warga WHERE nik=?", (p["nik"],), one=True)
    return render_template("pendaftaran/detail.html", p=p, ada=ada, STATUS_DAFTAR=STATUS_DAFTAR)


@bp.post("/pendaftaran/<int:pid>/aksi")
@roles_required("ketua")
def aksi(pid):
    p, u = _get(pid), current_user()
    act = choice("aksi", "aksi", ("setujui", "tolak"))
    if p["status"] != "menunggu":
        raise Invalid("Pendaftaran ini sudah diproses. Muat ulang halaman.")
    if not p["user_id"] or not scalar("SELECT 1 FROM users WHERE id=?", (p["user_id"],)):
        raise Invalid("Akun pendaftar tidak ditemukan (mungkin sudah dihapus Admin).")
    link = url_for("pendaftaran.detail", pid=pid)

    if act == "tolak":
        alasan = text("catatan", "Alasan penolakan", 300)
        db().execute("UPDATE pendaftaran SET status='ditolak', catatan=?, diproses_oleh=?, "
                     "diproses_pada=datetime('now','localtime') WHERE id=?", (alasan, u["id"], pid))
        db().commit()
        log("daftar_tolak", f"#{pid} {p['username']}")
        notify([p["user_id"]], "Pendaftaran ditolak", alasan)
        flash("Pendaftaran ditolak. Pendaftar dapat mendaftar ulang dengan data yang benar.", "ok")
        return redirect(url_for("pendaftaran.index"))

    catatan = text("catatan", "Catatan", 300, required=False)
    w_nik = q("SELECT * FROM warga WHERE nik=?", (p["nik"],), one=True)
    w_akun = q("SELECT * FROM warga WHERE user_id=?", (p["user_id"],), one=True)      # mis. kerangka kosong buatan Admin
    if w_nik and w_nik["user_id"] and w_nik["user_id"] != p["user_id"]:
        raise Invalid("NIK ini sudah terhubung dengan akun lain. Tolak pendaftaran atau periksa Data Warga.")
    if w_nik and w_akun and w_nik["id"] != w_akun["id"]:
        raise Invalid("Terdapat dua data warga yang bentrok untuk pendaftar ini. Rapikan dulu lewat menu Data Warga.")
    w = w_nik or w_akun
    try:
        if w:                                        # hubungkan ke data warga yang sudah ada; hanya isi kolom yang masih kosong
            isi = ("nik", "kk", "jk", "tempat_lahir", "tgl_lahir", "alamat", "telepon", "pekerjaan")
            sets = ", ".join(f"{c}=COALESCE(NULLIF({c},''),?)" for c in isi)
            db().execute(f"UPDATE warga SET user_id=?, {sets} WHERE id=?",
                         [p["user_id"], *[p[c] for c in isi], w["id"]])
        else:
            db().execute(
                "INSERT INTO warga(user_id,nik,kk,nama,jk,tempat_lahir,tgl_lahir,alamat,telepon,pekerjaan,status_tinggal) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (p["user_id"], p["nik"], p["kk"], p["nama"], p["jk"], p["tempat_lahir"], p["tgl_lahir"], p["alamat"],
                 p["telepon"], p["pekerjaan"], p["status_tinggal"]))
        db().execute("UPDATE users SET aktif=1 WHERE id=?", (p["user_id"],))
        db().execute("UPDATE pendaftaran SET status='disetujui', catatan=?, diproses_oleh=?, "
                     "diproses_pada=datetime('now','localtime') WHERE id=?", (catatan, u["id"], pid))
        db().commit()
    except Exception:
        db().rollback()
        raise
    log("daftar_setuju", f"#{pid} {p['username']}")
    notify([p["user_id"]], "Pendaftaran disetujui", "Akun Anda sudah aktif. Selamat datang di RUKUNIN!")
    flash(f"Pendaftaran {p['nama']} disetujui; akun sudah aktif dan data warga tersimpan.", "ok")
    return redirect(url_for("pendaftaran.index"))
