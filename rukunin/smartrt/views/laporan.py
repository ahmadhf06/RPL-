"""Laporan lingkungan: foto, lokasi, penanggung jawab, status."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..core import (ROLES, STAFF, STATUS, Invalid, can_see_laporan, choice, current_user, db, flt, log, notify, num, q,
                    roles_required, save_image, scalar, text, users_by_role)

bp = Blueprint("laporan", __name__, url_prefix="/laporan")
KATEGORI = ["Kebersihan", "Keamanan", "Infrastruktur", "Fasilitas Umum", "Sosial", "Lainnya"]


@bp.route("/")
@roles_required("warga", "ketua", "sekretaris", "bendahara", "humas")
def index():
    u, status = current_user(), request.args.get("status", "")
    where, args = [], []
    if u["role"] == "warga":
        where.append("l.user_id=?")
        args.append(u["id"])
    elif u["role"] != "ketua":                       # sekretaris/bendahara: hanya yang ditugaskan kepadanya
        where.append("l.pj_id=?")
        args.append(u["id"])
    if status in STATUS["laporan"]:
        where.append("l.status=?")
        args.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = q("SELECT l.*, p.nama AS pelapor, j.nama AS pj FROM laporan l JOIN users p ON p.id=l.user_id "
             f"LEFT JOIN users j ON j.id=l.pj_id {w} ORDER BY l.id DESC LIMIT 300", args)
    return render_template("laporan/list.html", rows=rows, status=status)


@bp.route("/baru", methods=["GET", "POST"])
@roles_required("warga")
def baru():
    if request.method == "POST":
        judul = text("judul", "Judul", 120)
        kategori = choice("kategori", "kategori", KATEGORI)
        desk = text("deskripsi", "Deskripsi", 2000)
        lokasi = text("lokasi", "Lokasi", 150)
        lat, lng = flt("lat", "Latitude", -90, 90), flt("lng", "Longitude", -180, 180)
        foto = save_image("foto")
        lid = db().execute("INSERT INTO laporan(user_id,judul,kategori,deskripsi,lokasi,lat,lng,foto) VALUES(?,?,?,?,?,?,?,?)",
                           (current_user()["id"], judul, kategori, desk, lokasi, lat, lng, foto)).lastrowid
        db().commit()
        log("laporan_baru", f"#{lid} {judul}")
        notify(users_by_role("ketua"), "Laporan lingkungan baru", f"{kategori}: {judul}", url_for("laporan.detail", lid=lid))
        flash("Laporan terkirim ke Ketua RT.", "ok")
        return redirect(url_for("laporan.detail", lid=lid))
    return render_template("laporan/form.html", kategori=KATEGORI)


def _get(lid):
    lap = q("SELECT l.*, p.nama AS pelapor, j.nama AS pj FROM laporan l JOIN users p ON p.id=l.user_id "
            "LEFT JOIN users j ON j.id=l.pj_id WHERE l.id=?", (lid,), one=True)
    if not lap:
        abort(404)
    if not can_see_laporan(current_user(), lap):
        abort(403)
    return lap


@bp.route("/<int:lid>")
@roles_required("warga", "ketua", "sekretaris", "bendahara", "humas")
def detail(lid):
    lap, u = _get(lid), current_user()
    can_edit = u["role"] == "ketua" or lap["pj_id"] == u["id"]
    staf = [(r["id"], f"{r['nama']} ({ROLES[r['role']]})") for r in q(
        "SELECT id, nama, role FROM users WHERE aktif=1 AND role IN ('ketua','sekretaris','bendahara','humas') ORDER BY role, nama")]
    opsi_status = [(k, v[0]) for k, v in STATUS["laporan"].items()]
    return render_template("laporan/detail.html", lap=lap, can_edit=can_edit, staf=staf, opsi_status=opsi_status)


@bp.post("/<int:lid>/update")
@roles_required("ketua", "sekretaris", "bendahara", "humas")
def update(lid):
    lap, u = _get(lid), current_user()
    if not (u["role"] == "ketua" or lap["pj_id"] == u["id"]):
        abort(403)
    status = choice("status", "status", STATUS["laporan"])
    catatan = text("catatan", "Catatan", 500, required=False)
    pj = lap["pj_id"]
    if u["role"] == "ketua":                         # hanya Ketua RT yang menunjuk penanggung jawab
        pj = num("pj_id", "Penanggung jawab", 1, 10 ** 9, required=False)
        if pj and not scalar("SELECT 1 FROM users WHERE id=? AND aktif=1 AND role IN ('ketua','sekretaris','bendahara','humas')", (pj,)):
            raise Invalid("Penanggung jawab tidak valid.")
    db().execute("UPDATE laporan SET status=?, catatan=?, pj_id=?, updated_at=datetime('now','localtime') WHERE id=?",
                 (status, catatan, pj, lid))
    db().commit()
    log("laporan_update", f"#{lid} -> {status}")
    link = url_for("laporan.detail", lid=lid)
    notify([lap["user_id"]], "Status laporan Anda diperbarui", f"{lap['judul']}: {STATUS['laporan'][status][0]}", link)
    if pj and pj != lap["pj_id"]:
        notify([pj], "Anda ditunjuk menangani laporan", lap["judul"], link)
    flash("Laporan diperbarui.", "ok")
    return redirect(link)
