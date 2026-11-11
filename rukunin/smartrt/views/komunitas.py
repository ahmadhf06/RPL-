"""Pengumuman, jadwal ronda, aspirasi, voting, dan presensi QR Code."""
import secrets
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from ..core import (Invalid, choice, current_user, datestr, db, ex, log, login_required, notify, num, q, roles_required,
                    scalar, text, users_by_role)

try:
    import segno
except ImportError:          # aplikasi tetap jalan; hanya gambar QR yang tidak tampil
    segno = None

bp = Blueprint("komunitas", __name__)

NON_ADMIN = ("ketua", "sekretaris", "bendahara", "humas", "warga")   # Admin Sistem tidak memakai presensi QR


# ---------------------------------------------------------------- pengumuman
@bp.route("/pengumuman")
@login_required
def pengumuman():
    rows = q("SELECT p.*, u.nama AS penulis FROM pengumuman p LEFT JOIN users u ON u.id=p.author_id "
             "ORDER BY p.penting DESC, p.id DESC LIMIT 100")
    return render_template("komunitas/pengumuman.html", rows=rows)


@bp.post("/pengumuman")
@roles_required("ketua", "humas")
def pengumuman_add():
    judul, isi = text("judul", "Judul", 120), text("isi", "Isi pengumuman", 3000)
    penting = 1 if request.form.get("penting") else 0
    u = current_user()
    ex("INSERT INTO pengumuman(judul,isi,penting,author_id) VALUES(?,?,?,?)", (judul, isi, penting, u["id"]))
    log("pengumuman_baru", judul)
    notify([r["id"] for r in q("SELECT id FROM users WHERE aktif=1 AND id<>?", (u["id"],))],
           "Pengumuman baru" + (" (PENTING)" if penting else ""), judul, url_for("komunitas.pengumuman"))
    flash("Pengumuman dipublikasikan.", "ok")
    return redirect(url_for("komunitas.pengumuman"))


@bp.post("/pengumuman/<int:pid>/hapus")
@roles_required("ketua", "humas")
def pengumuman_hapus(pid):
    p, u = q("SELECT author_id FROM pengumuman WHERE id=?", (pid,), one=True), current_user()
    if not p:
        abort(404)
    if u["role"] == "humas" and p["author_id"] != u["id"]:      # Humas hanya boleh menghapus pengumuman buatannya sendiri
        abort(403)
    ex("DELETE FROM pengumuman WHERE id=?", (pid,))
    log("pengumuman_hapus", f"#{pid}")
    return redirect(url_for("komunitas.pengumuman"))


# ---------------------------------------------------------------- jadwal ronda
@bp.route("/ronda")
@roles_required("ketua", "sekretaris", "bendahara", "humas", "warga")
def ronda():
    base = "SELECT r.*, w.nama, w.user_id FROM ronda r JOIN warga w ON w.id=r.warga_id "
    mendatang = q(base + "WHERE r.tanggal>=date('now','localtime') ORDER BY r.tanggal, r.id")
    lalu = q(base + "WHERE r.tanggal<date('now','localtime') ORDER BY r.tanggal DESC, r.id DESC LIMIT 15")
    warga = q("SELECT id, nama FROM warga WHERE aktif=1 ORDER BY nama") if current_user()["role"] in ("ketua", "sekretaris") else []
    return render_template("komunitas/ronda.html", mendatang=mendatang, lalu=lalu, warga=warga, hari_ini=date.today().isoformat())


@bp.post("/ronda")
@roles_required("ketua", "sekretaris")
def ronda_add():
    tanggal, pos = datestr("tanggal", "ronda"), text("pos", "Pos", 60)
    ids = {int(x) for x in request.form.getlist("warga_ids") if x.isdigit()}
    valid = [r for r in ids if scalar("SELECT 1 FROM warga WHERE id=? AND aktif=1", (r,))]
    if not valid:
        raise Invalid("Pilih minimal satu warga.")
    for wid in valid:
        db().execute("INSERT INTO ronda(tanggal,warga_id,pos) VALUES(?,?,?)", (tanggal, wid, pos))
    db().commit()
    akun = [scalar("SELECT user_id FROM warga WHERE id=?", (w,)) for w in valid]
    notify(akun, "Jadwal ronda baru", f"Anda bertugas ronda pada {tanggal} di {pos}.", url_for("komunitas.ronda"))
    log("ronda_tambah", f"{tanggal} x{len(valid)}")
    flash("Jadwal ronda ditambahkan.", "ok")
    return redirect(url_for("komunitas.ronda"))


@bp.post("/ronda/<int:rid>/hapus")
@roles_required("ketua", "sekretaris")
def ronda_hapus(rid):
    ex("DELETE FROM ronda WHERE id=?", (rid,))
    return redirect(url_for("komunitas.ronda"))


# ---------------------------------------------------------------- aspirasi
@bp.route("/aspirasi")
@roles_required("warga", "ketua", "humas")
def aspirasi():
    u = current_user()
    if u["role"] == "warga":
        rows = q("SELECT a.*, u.nama AS pengirim FROM aspirasi a JOIN users u ON u.id=a.user_id WHERE a.user_id=? ORDER BY a.id DESC", (u["id"],))
    else:
        rows = q("SELECT a.*, u.nama AS pengirim FROM aspirasi a JOIN users u ON u.id=a.user_id ORDER BY a.status, a.id DESC LIMIT 200")
    return render_template("komunitas/aspirasi.html", rows=rows)


@bp.post("/aspirasi")
@roles_required("warga")
def aspirasi_add():
    judul, isi = text("judul", "Judul", 120), text("isi", "Aspirasi", 2000)
    ex("INSERT INTO aspirasi(user_id,judul,isi) VALUES(?,?,?)", (current_user()["id"], judul, isi))
    notify(users_by_role("ketua", "humas"), "Aspirasi warga baru", judul, url_for("komunitas.aspirasi"))
    flash("Aspirasi terkirim.", "ok")
    return redirect(url_for("komunitas.aspirasi"))


@bp.post("/aspirasi/<int:aid>/tanggapi")
@roles_required("ketua", "humas")
def aspirasi_tanggapi(aid):
    a = q("SELECT * FROM aspirasi WHERE id=?", (aid,), one=True)
    if not a:
        abort(404)
    tanggapan = text("tanggapan", "Tanggapan", 1000)
    ex("UPDATE aspirasi SET status='ditanggapi', tanggapan=?, responded_by=?, responded_at=datetime('now','localtime') WHERE id=?",
       (tanggapan, current_user()["id"], aid))
    notify([a["user_id"]], "Aspirasi Anda ditanggapi", a["judul"], url_for("komunitas.aspirasi"))
    flash("Tanggapan terkirim.", "ok")
    return redirect(url_for("komunitas.aspirasi"))


# ---------------------------------------------------------------- voting
@bp.route("/voting")
@roles_required("ketua", "sekretaris", "bendahara", "humas", "warga")
def voting():
    u, today, daftar = current_user(), date.today().isoformat(), []
    for v in q("SELECT * FROM voting ORDER BY id DESC LIMIT 50"):
        opsi = q("SELECT o.id, o.teks, COUNT(s.id) AS jumlah FROM voting_opsi o LEFT JOIN voting_suara s ON s.opsi_id=o.id "
                 "WHERE o.voting_id=? GROUP BY o.id ORDER BY o.id", (v["id"],))
        total = sum(o["jumlah"] for o in opsi)
        pilihan = scalar("SELECT opsi_id FROM voting_suara WHERE voting_id=? AND user_id=?", (v["id"], u["id"]))
        terbuka = v["status"] == "aktif" and v["berakhir"] >= today
        daftar.append(dict(v=v, total=total, terbuka=terbuka, pilihan=pilihan,
                           bisa_pilih=terbuka and u["role"] == "warga" and not pilihan,
                           tampil_hasil=(u["role"] in ("ketua", "humas")) or bool(pilihan) or not terbuka,
                           opsi=[dict(o, persen=round(o["jumlah"] * 100 / total) if total else 0) for o in opsi]))
    return render_template("komunitas/voting.html", daftar=daftar, hari_ini=today)


@bp.post("/voting")
@roles_required("ketua")
def voting_add():
    judul, desk = text("judul", "Judul", 120), text("deskripsi", "Deskripsi", 500, required=False)
    berakhir = datestr("berakhir", "berakhir")
    if berakhir < date.today().isoformat():
        raise Invalid("Tanggal berakhir tidak boleh di masa lalu.")
    opsi = [o.strip() for o in (request.form.get("opsi") or "").splitlines() if o.strip()]
    if not 2 <= len(opsi) <= 8 or any(len(o) > 100 for o in opsi):
        raise Invalid("Isi 2-8 pilihan, satu per baris (maksimal 100 karakter).")
    vid = db().execute("INSERT INTO voting(judul,deskripsi,berakhir,created_by) VALUES(?,?,?,?)",
                       (judul, desk, berakhir, current_user()["id"])).lastrowid
    for o in opsi:
        db().execute("INSERT INTO voting_opsi(voting_id,teks) VALUES(?,?)", (vid, o))
    db().commit()
    log("voting_baru", judul)
    notify(users_by_role("warga"), "Voting baru", judul, url_for("komunitas.voting"))
    flash("Voting dibuka.", "ok")
    return redirect(url_for("komunitas.voting"))


@bp.post("/voting/<int:vid>/pilih")
@roles_required("warga")
def voting_pilih(vid):
    v = q("SELECT * FROM voting WHERE id=?", (vid,), one=True)
    if not v:
        abort(404)
    if v["status"] != "aktif" or v["berakhir"] < date.today().isoformat():
        raise Invalid("Voting sudah ditutup.")
    oid = num("opsi", "Pilihan", 1, 10 ** 9)
    if not scalar("SELECT 1 FROM voting_opsi WHERE id=? AND voting_id=?", (oid, vid)):
        raise Invalid("Pilihan tidak valid.")
    try:
        ex("INSERT INTO voting_suara(voting_id,opsi_id,user_id) VALUES(?,?,?)", (vid, oid, current_user()["id"]))
    except Exception:
        raise Invalid("Anda sudah memberikan suara pada voting ini.")
    flash("Suara Anda tercatat. Terima kasih!", "ok")
    return redirect(url_for("komunitas.voting"))


@bp.post("/voting/<int:vid>/tutup")
@roles_required("ketua")
def voting_tutup(vid):
    ex("UPDATE voting SET status='ditutup' WHERE id=?", (vid,))
    log("voting_tutup", f"#{vid}")
    return redirect(url_for("komunitas.voting"))


# ---------------------------------------------------------------- kegiatan & presensi QR
JENIS_KEGIATAN = ["Rapat", "Kerja Bakti", "Ronda", "Acara Warga", "Lainnya"]


@bp.route("/kegiatan")
@roles_required(*NON_ADMIN)
def kegiatan():
    u = current_user()
    rows = q("SELECT k.*, (SELECT COUNT(*) FROM presensi p WHERE p.kegiatan_id=k.id) AS hadir, "
             "(SELECT 1 FROM presensi p WHERE p.kegiatan_id=k.id AND p.user_id=?) AS saya "
             "FROM kegiatan k ORDER BY k.tanggal DESC, k.id DESC LIMIT 100", (u["id"],))
    kegiatan_list = []
    for k in rows:
        item = dict(k)
        item_url = _presensi_url(k["token"])
        item["url"] = item_url
        if segno:
            item["svg"] = Markup(segno.make(item_url, error="m").svg_inline(scale=5, border=2, dark="#064e3b", light="#ffffff"))
        else:
            item["svg"] = None
        kegiatan_list.append(item)
    return render_template("komunitas/kegiatan.html", rows=kegiatan_list, jenis=JENIS_KEGIATAN, hari_ini=date.today().isoformat())


@bp.post("/kegiatan")
@roles_required("ketua", "sekretaris", "humas")
def kegiatan_add():
    nama, jenis = text("nama", "Nama kegiatan", 100), choice("jenis", "jenis", JENIS_KEGIATAN)
    tanggal, lokasi = datestr("tanggal", "kegiatan"), text("lokasi", "Lokasi", 120)
    kid = ex("INSERT INTO kegiatan(nama,jenis,tanggal,lokasi,token,created_by) VALUES(?,?,?,?,?,?)",
             (nama, jenis, tanggal, lokasi, secrets.token_urlsafe(9), current_user()["id"]))
    log("kegiatan_baru", nama)
    notify([r["id"] for r in q("SELECT id FROM users WHERE aktif=1 AND role<>'admin' AND id<>?", (current_user()["id"],))],
           "Kegiatan baru", f"{nama} - {tanggal}, {lokasi}", url_for("komunitas.kegiatan"))
    return redirect(url_for("komunitas.kegiatan_detail", kid=kid))


def _presensi_url(token):
    base = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    path = url_for("komunitas.presensi", token=token)
    return base + path if base else url_for("komunitas.presensi", token=token, _external=True)


@bp.route("/kegiatan/<int:kid>")
@roles_required(*NON_ADMIN)
def kegiatan_detail(kid):
    k = q("SELECT * FROM kegiatan WHERE id=?", (kid,), one=True)
    if not k:
        abort(404)
    url = _presensi_url(k["token"])
    if segno:
        svg = Markup(segno.make(url, error="m").svg_inline(scale=6, border=2, dark="#064e3b", light="#ffffff"))
    else:
        svg = Markup('<p class="flash error">Modul QR belum terpasang. Jalankan: <b>pip install segno</b> lalu restart server. '
                     'Sementara itu, bagikan tautan di bawah ini.</p>')
    hadir = q("SELECT p.waktu, u.nama, u.role FROM presensi p JOIN users u ON u.id=p.user_id WHERE p.kegiatan_id=? ORDER BY p.waktu", (kid,))
    sudah = scalar("SELECT 1 FROM presensi WHERE kegiatan_id=? AND user_id=?", (kid, current_user()["id"]))
    return render_template("komunitas/kegiatan_detail.html", k=k, svg=svg, url=url, hadir=hadir, sudah=sudah)


@bp.post("/kegiatan/<int:kid>/toggle")
@roles_required("ketua", "sekretaris", "humas")
def kegiatan_toggle(kid):
    ex("UPDATE kegiatan SET aktif=1-aktif WHERE id=?", (kid,))
    return redirect(url_for("komunitas.kegiatan_detail", kid=kid))


@bp.route("/presensi/<token>", methods=["GET", "POST"])
@roles_required(*NON_ADMIN)
def presensi(token):
    """Tujuan QR Code. GET hanya menampilkan konfirmasi; pencatatan lewat POST (terlindungi CSRF)."""
    k = q("SELECT * FROM kegiatan WHERE token=?", (token,), one=True)
    if not k:
        abort(404)
    u = current_user()
    sudah = scalar("SELECT 1 FROM presensi WHERE kegiatan_id=? AND user_id=?", (k["id"], u["id"]))
    if request.method == "POST":
        if not k["aktif"]:
            raise Invalid("Presensi untuk kegiatan ini sudah ditutup.")
        ex("INSERT OR IGNORE INTO presensi(kegiatan_id,user_id) VALUES(?,?)", (k["id"], u["id"]))
        log("presensi", k["nama"])
        flash(f"Kehadiran Anda di “{k['nama']}” tercatat.", "ok")
        return redirect(url_for("komunitas.kegiatan"))
    return render_template("komunitas/presensi.html", k=k, sudah=sudah)
