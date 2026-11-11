"""Pendataan warga. Ketua RT mengelola; Sekretaris & Bendahara hanya membaca."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..core import Invalid, choice, datestr, ex, log, q, roles_required, scalar, text

bp = Blueprint("warga", __name__, url_prefix="/warga")


@bp.route("/")
@roles_required("ketua", "sekretaris", "bendahara")
def index():
    cari = (request.args.get("q") or "").strip()[:50]
    if cari:
        like = f"%{cari}%"
        rows = q("SELECT w.*, u.username FROM warga w LEFT JOIN users u ON u.id=w.user_id "
                 "WHERE w.nama LIKE ? OR w.nik LIKE ? OR w.kk LIKE ? OR w.alamat LIKE ? ORDER BY w.nama LIMIT 300",
                 (like, like, like, like))
    else:
        rows = q("SELECT w.*, u.username FROM warga w LEFT JOIN users u ON u.id=w.user_id ORDER BY w.nama LIMIT 300")
    return render_template("warga/list.html", rows=rows, cari=cari)


def _simpan(wid=None):
    d = dict(
        nik=text("nik", "NIK", 16, pattern=r"\d{16}"),
        kk=text("kk", "No. KK", 16, required=False, pattern=r"\d{16}"),
        nama=text("nama", "Nama lengkap", 100),
        jk=choice("jk", "jenis kelamin", ("L", "P")),
        tempat_lahir=text("tempat_lahir", "Tempat lahir", 60, required=False),
        tgl_lahir=datestr("tgl_lahir", "lahir", required=False),
        alamat=text("alamat", "Alamat", 150),
        telepon=text("telepon", "Telepon", 20, required=False, pattern=r"[0-9+\- ]{8,20}"),
        pekerjaan=text("pekerjaan", "Pekerjaan", 60, required=False),
        status_tinggal=choice("status_tinggal", "status tinggal", ("Tetap", "Kontrak", "Kos")),
        aktif=1 if request.form.get("aktif") else 0)
    dup = scalar("SELECT id FROM warga WHERE nik=? AND id<>?", (d["nik"], wid or 0))
    if dup:
        raise Invalid("NIK sudah terdaftar pada warga lain.")
    cols = list(d)
    if wid:
        ex(f"UPDATE warga SET {', '.join(c + '=?' for c in cols)} WHERE id=?", [*d.values(), wid])
        log("warga_ubah", d["nama"])
    else:
        ex(f"INSERT INTO warga({','.join(cols)}) VALUES({','.join('?' * len(cols))})", list(d.values()))
        log("warga_baru", d["nama"])


@bp.route("/baru", methods=["GET", "POST"])
@roles_required("ketua")
def baru():
    if request.method == "POST":
        _simpan()
        flash("Data warga ditambahkan.", "ok")
        return redirect(url_for("warga.index"))
    return render_template("warga/form.html", w=None)


@bp.route("/<int:wid>/edit", methods=["GET", "POST"])
@roles_required("ketua")
def edit(wid):
    w = q("SELECT * FROM warga WHERE id=?", (wid,), one=True)
    if not w:
        abort(404)
    if request.method == "POST":
        _simpan(wid)
        flash("Data warga diperbarui.", "ok")
        return redirect(url_for("warga.index"))
    return render_template("warga/form.html", w=w)
