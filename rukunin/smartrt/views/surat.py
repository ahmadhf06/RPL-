"""Persuratan: Warga -> Sekretaris (periksa, draf, nomor) -> Ketua RT (setujui) -> Sekretaris (arsip) -> Selesai."""
import secrets
import sqlite3
from datetime import date

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from markupsafe import Markup

try:
    import segno
except ImportError:          # tanpa modul QR, surat tetap bisa dicetak (tanpa gambar QR)
    segno = None

from ..core import (Invalid, STATUS, choice, current_user, db, get_settings, log, my_warga_id, notify, q,
                    roles_required, scalar, text, user_of_warga, users_by_role)

bp = Blueprint("surat", __name__, url_prefix="/surat")
verif_bp = Blueprint("verifikasi", __name__)          # halaman publik (tanpa login) untuk memeriksa keaslian surat
JENIS = ["Surat Pengantar KTP/KK", "Surat Keterangan Domisili", "Surat Keterangan Tidak Mampu",
         "Surat Keterangan Usaha", "Surat Pengantar SKCK", "Surat Keterangan Kematian",
         "Surat Pengantar Nikah", "Surat Lainnya"]
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
# (peran, aksi) -> (status asal yang diizinkan, status tujuan).  Sekretaris TIDAK punya aksi 'setujui'.
TRANS = {("sekretaris", "teruskan"): ("diajukan", "menunggu_ketua"),
         ("sekretaris", "tolak"): ("diajukan", "ditolak"),
         ("sekretaris", "arsipkan"): ("disetujui", "selesai"),
         ("ketua", "setujui"): ("menunggu_ketua", "disetujui"),
         ("ketua", "tolak"): ("menunggu_ketua", "ditolak")}
CETAK_OK = ("menunggu_ketua", "disetujui", "selesai")


def _get(sid):
    s = q("SELECT s.*, w.nama, w.nik, w.alamat, w.tempat_lahir, w.tgl_lahir, w.pekerjaan, w.user_id AS wuser "
          "FROM surat s JOIN warga w ON w.id=s.warga_id WHERE s.id=?", (sid,), one=True)
    if not s:
        abort(404)
    u = current_user()
    if u["role"] == "warga" and s["wuser"] != u["id"]:
        abort(403)                                   # warga hanya boleh melihat suratnya sendiri
    return s


def _saran_nomor():
    now, cfg = date.today(), get_settings()
    n = (scalar("SELECT COUNT(*) FROM surat WHERE nomor IS NOT NULL AND substr(updated_at,1,4)=?", (str(now.year),)) or 0) + 1
    rt = (cfg.get("nama_rt") or "RT").split("/")[0].strip().replace(" ", "")
    while True:
        nomor = f"{n:03d}/{rt}/{ROMAN[now.month - 1]}/{now.year}"
        if not scalar("SELECT 1 FROM surat WHERE nomor=?", (nomor,)):
            return nomor
        n += 1


def _draf(s):
    cfg = get_settings()
    return (f"Yang bertanda tangan di bawah ini, Ketua {cfg.get('nama_rt', 'RT')}, Kelurahan {cfg.get('kelurahan', '-')}, "
            f"Kecamatan {cfg.get('kecamatan', '-')}, menerangkan bahwa:\n\n"
            f"Nama           : {s['nama']}\nNIK            : {s['nik'] or '-'}\n"
            f"Tempat/Tgl Lahir : {s['tempat_lahir'] or '-'}, {s['tgl_lahir'] or '-'}\n"
            f"Pekerjaan      : {s['pekerjaan'] or '-'}\nAlamat         : {s['alamat'] or '-'}\n\n"
            f"Orang tersebut benar warga kami yang berdomisili di alamat di atas. Surat ini dibuat untuk keperluan: "
            f"{s['keperluan']}.\n\nDemikian surat ini dibuat untuk dapat dipergunakan sebagaimana mestinya.")


@bp.route("/")
@roles_required("warga", "sekretaris", "ketua")
def index():
    u = current_user()
    status = request.args.get("status", "")
    where, args = [], []
    if u["role"] == "warga":
        where.append("s.warga_id=?")
        args.append(my_warga_id() or 0)
    if status in STATUS["surat"]:
        where.append("s.status=?")
        args.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = q(f"SELECT s.*, w.nama FROM surat s JOIN warga w ON w.id=s.warga_id {w} ORDER BY s.id DESC LIMIT 300", args)
    return render_template("surat/list.html", rows=rows, status=status)


@bp.route("/baru", methods=["GET", "POST"])
@roles_required("warga")
def baru():
    wid = my_warga_id()
    if not wid:
        flash("Akun Anda belum terhubung ke data warga. Hubungi Ketua RT.", "error")
        return redirect(url_for("surat.index"))
    if request.method == "POST":
        jenis = choice("jenis", "jenis surat", JENIS)
        keperluan = text("keperluan", "Keperluan", 200)
        ket = text("keterangan", "Keterangan tambahan", 500, required=False)
        sid = db().execute("INSERT INTO surat(warga_id,jenis,keperluan,keterangan) VALUES(?,?,?,?)",
                           (wid, jenis, keperluan, ket)).lastrowid
        db().execute("INSERT INTO surat_log(surat_id,status,oleh,catatan) VALUES(?,?,?,?)",
                     (sid, "diajukan", current_user()["id"], "Pengajuan dibuat"))
        db().commit()
        log("surat_ajukan", f"#{sid} {jenis}")
        notify(users_by_role("sekretaris"), "Pengajuan surat baru", f"{jenis} - {keperluan}", url_for("surat.detail", sid=sid))
        flash("Pengajuan surat terkirim ke Sekretaris.", "ok")
        return redirect(url_for("surat.detail", sid=sid))
    return render_template("surat/form.html", jenis=JENIS)


@bp.route("/<int:sid>")
@roles_required("warga", "sekretaris", "ketua")
def detail(sid):
    s = _get(sid)
    logs = q("SELECT l.*, u.nama, u.role FROM surat_log l LEFT JOIN users u ON u.id=l.oleh WHERE l.surat_id=? ORDER BY l.id", (sid,))
    u = current_user()
    # Cetak: warga (setelah selesai) dan Sekretaris saja; Ketua RT hanya melihat/menyetujui
    can_print = (u["role"] == "warga" and s["status"] == "selesai") or (u["role"] == "sekretaris" and s["status"] in CETAK_OK)
    return render_template("surat/detail.html", s=s, logs=logs, can_print=can_print,
                           draf=s["draf"] or _draf(s), saran=s["nomor"] or _saran_nomor())


@bp.post("/<int:sid>/aksi")
@roles_required("sekretaris", "ketua")
def aksi(sid):
    u, s = current_user(), _get(sid)
    act = request.form.get("aksi", "")
    rule = TRANS.get((u["role"], act))
    if not rule:
        abort(403)                                   # mis. Sekretaris mencoba 'setujui'
    asal, tujuan = rule
    if s["status"] != asal:
        raise Invalid("Status surat sudah berubah. Muat ulang halaman.")
    note = text("catatan", "Catatan", 500, required=(act == "tolak"))
    sets, args = ["status=?", "catatan=?", "updated_at=datetime('now','localtime')"], [tujuan, note]
    if act == "setujui":
        # Tanda tangan digital: nama penanda tangan, waktu, gambar ttd, dan kode verifikasi DIKUNCI saat disetujui,
        # sehingga surat lama tidak berubah walaupun nanti Ketua RT diganti.
        sets += ["ttd_token=?", "ttd_nama=?", "ttd_pada=datetime('now','localtime')", "ttd_gambar=?"]
        args += [secrets.token_hex(16), get_settings().get("nama_ttd") or u["nama"], u["ttd_gambar"]]
    if act == "teruskan":
        draf = text("draf", "Draf surat", 4000)
        nomor = text("nomor", "Nomor surat", 50, pattern=r"[\w./\- ]+")
        if len(draf) < 30:
            raise Invalid("Draf surat terlalu pendek.")
        sets += ["draf=?", "nomor=?"]
        args += [draf, nomor]
    try:
        db().execute(f"UPDATE surat SET {', '.join(sets)} WHERE id=?", [*args, sid])
    except sqlite3.IntegrityError:
        raise Invalid("Nomor surat sudah dipakai surat lain.")
    db().execute("INSERT INTO surat_log(surat_id,status,oleh,catatan) VALUES(?,?,?,?)", (sid, tujuan, u["id"], note))
    db().commit()
    log(f"surat_{act}", f"#{sid}")
    link, warga_user = url_for("surat.detail", sid=sid), user_of_warga(s["warga_id"])
    if act == "teruskan":
        notify(users_by_role("ketua"), "Surat menunggu persetujuan", f"{s['jenis']} - {s['nama']}", link)
        notify([warga_user], "Surat Anda diproses", "Pengajuan lolos pemeriksaan dan menunggu persetujuan Ketua RT.", link)
    elif act == "setujui":
        notify([warga_user], "Surat disetujui Ketua RT", "Surat sedang diarsipkan oleh Sekretaris.", link)
        notify(users_by_role("sekretaris"), "Surat disetujui", f"{s['jenis']} - {s['nama']} siap diarsipkan.", link)
    elif act == "tolak":
        notify([warga_user], "Pengajuan surat ditolak", note, link)
        if u["role"] == "ketua":
            notify(users_by_role("sekretaris"), "Surat ditolak Ketua RT", f"{s['jenis']} - {s['nama']}: {note}", link)
    else:
        notify([warga_user], "Surat selesai", "Surat Anda sudah selesai dan dapat dicetak.", link)
    flash("Status surat diperbarui.", "ok")
    return redirect(link)


@bp.route("/<int:sid>/cetak")
@roles_required("warga", "sekretaris")          # Ketua RT hanya melihat, tidak mencetak
def cetak(sid):
    s, u = _get(sid), current_user()
    if not s["draf"] or (u["role"] == "warga" and s["status"] != "selesai") or s["status"] not in CETAK_OK:
        abort(403)
    cfg = get_settings()
    # Nama penanda tangan: yang tercatat saat disetujui; untuk draf yang belum disetujui, Ketua RT yang aktif sekarang
    ketua = s["ttd_nama"] or cfg.get("nama_ttd") or scalar("SELECT nama FROM users WHERE role='ketua' AND aktif=1 ORDER BY id DESC LIMIT 1") or "Ketua RT"
    setuju = q("SELECT created_at FROM surat_log WHERE surat_id=? AND status='disetujui' ORDER BY id DESC LIMIT 1", (sid,), one=True)
    qr, verif = "", ""
    if s["ttd_token"]:
        verif = _verif_url(s["ttd_token"])
        if segno:
            qr = Markup(segno.make(verif, error="m").svg_inline(scale=3, border=1, dark="#111111", light="#ffffff"))
    return render_template("surat/cetak.html", s=s, ketua=ketua, setuju=setuju, qr=qr, verif=verif)


def _verif_url(token):
    base = current_app.config.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base:
        return base + url_for("verifikasi.cek", token=token)
    return url_for("verifikasi.cek", token=token, _external=True)


def _samar(nama):
    """'Siti Aminah' -> 'S*** A*****' : halaman verifikasi bersifat publik, nama pemohon tidak ditampilkan utuh."""
    return " ".join(k[0] + "*" * (len(k) - 1) for k in (nama or "").split())


@verif_bp.get("/verifikasi/<token>")
def cek(token):
    s = None
    if len(token) == 32 and all(c in "0123456789abcdef" for c in token):
        s = q("SELECT s.jenis, s.nomor, s.status, s.ttd_nama, s.ttd_pada, w.nama FROM surat s JOIN warga w ON w.id=s.warga_id "
              "WHERE s.ttd_token=?", (token,), one=True)
    if not s:
        return render_template("surat/verifikasi.html", s=None), 404
    return render_template("surat/verifikasi.html", s=s, pemohon=_samar(s["nama"]))
