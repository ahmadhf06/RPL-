"""Keuangan RT: kas, tagihan iuran, bukti pembayaran, verifikasi, rekap saldo."""
import csv
import io
import re
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from .. import ui
from ..core import (STATUS, Invalid, choice, current_user, datestr, db, get_settings, log, monthly, my_warga_id,
                    notify, num, q, roles_required, save_image, saldo, scalar, text, user_of_warga, users_by_role)

bp = Blueprint("keuangan", __name__, url_prefix="/keuangan")
tagihan_bp = Blueprint("tagihan", __name__)
transparan_bp = Blueprint("transparansi", __name__)
KAT_MASUK = ["Iuran Warga", "Donasi", "Saldo Awal", "Lainnya"]
KAT_KELUAR = ["Kebersihan", "Keamanan", "Perbaikan", "Kegiatan Warga", "Administrasi", "Lainnya"]
METODE_PILIHAN = ["Transfer Bank BCA", "QR Dana", "Tunai via perwakilan"]
METODE = METODE_PILIHAN + ["Transfer Bank", "QRIS", "Tunai"]


def _bulan_arg(name="bulan"):
    v = request.args.get(name, "")
    return v if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v) else ""


# ---------------------------------------------------------------- kas
def _filter_transaksi():
    bulan, tipe = _bulan_arg(), request.args.get("tipe", "")
    where, args = [], []
    if bulan:
        where.append("substr(t.tanggal,1,7)=?")
        args.append(bulan)
    if tipe in ("pemasukan", "pengeluaran"):
        where.append("t.tipe=?")
        args.append(tipe)
    return bulan, tipe, ("WHERE " + " AND ".join(where)) if where else "", args


@bp.route("/")
@roles_required("ketua", "bendahara")
def index():
    bulan, tipe, w, args = _filter_transaksi()
    rows = q("SELECT t.*, u.nama AS oleh FROM transaksi t LEFT JOIN users u ON u.id=t.created_by "
             f"{w} ORDER BY t.tanggal DESC, t.id DESC LIMIT 300", args)
    masuk = scalar("SELECT COALESCE(SUM(nominal),0) FROM transaksi WHERE tipe='pemasukan'")
    keluar = scalar("SELECT COALESCE(SUM(nominal),0) FROM transaksi WHERE tipe='pengeluaran'")
    m_masuk = monthly("pemasukan")
    m_keluar = monthly("pengeluaran")
    
    # Gabungan cashflow 6 bulan untuk grafik keuangan komprehensif
    cashflow_6bln = []
    keluar_dict = dict(m_keluar)
    for b_lbl, m_val in m_masuk:
        k_val = keluar_dict.get(b_lbl, 0)
        cashflow_6bln.append({
            "bulan": b_lbl,
            "masuk": m_val,
            "keluar": k_val,
            "net": m_val - k_val
        })

    # Distribusi pengeluaran & pemasukan per kategori
    dist_keluar = q("SELECT kategori, COALESCE(SUM(nominal),0) total FROM transaksi "
                    "WHERE tipe='pengeluaran' GROUP BY kategori ORDER BY total DESC")
    dist_masuk = q("SELECT kategori, COALESCE(SUM(nominal),0) total FROM transaksi "
                   "WHERE tipe='pemasukan' GROUP BY kategori ORDER BY total DESC")

    return render_template("keuangan/index.html", rows=rows, bulan=bulan, tipe=tipe, masuk=masuk, keluar=keluar, saldo=saldo(),
                           chart_masuk=m_masuk, chart_keluar=m_keluar, cashflow_6bln=cashflow_6bln,
                           dist_keluar=dist_keluar, dist_masuk=dist_masuk,
                           kat_masuk=KAT_MASUK, kat_keluar=KAT_KELUAR, hari_ini=date.today().isoformat())


@bp.post("/transaksi")
@roles_required("bendahara")
def transaksi_add():
    tipe = choice("tipe", "jenis transaksi", ("pemasukan", "pengeluaran"))
    kategori = choice("kategori", "kategori", KAT_MASUK if tipe == "pemasukan" else KAT_KELUAR)
    nominal = num("nominal", "Nominal", 1, 10 ** 10)
    ket = text("keterangan", "Keterangan", 200)
    tanggal = datestr("tanggal", "transaksi")
    if tipe == "pengeluaran" and nominal > saldo():
        raise Invalid("Pengeluaran melebihi saldo kas saat ini.")
    db().execute("INSERT INTO transaksi(tipe,kategori,nominal,keterangan,tanggal,created_by) VALUES(?,?,?,?,?,?)",
                 (tipe, kategori, nominal, ket, tanggal, current_user()["id"]))
    db().commit()
    log("transaksi", f"{tipe} {nominal} {kategori}")
    notify(users_by_role("ketua"), f"Transaksi {tipe} dicatat", f"{kategori}: {ket}", url_for("keuangan.index"))
    flash("Transaksi dicatat.", "ok")
    return redirect(url_for("keuangan.index"))


def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v      # cegah CSV/formula injection


@bp.get("/export.csv")
@roles_required("ketua", "bendahara")
def export():
    _, _, w, args = _filter_transaksi()
    rows = q(f"SELECT t.* FROM transaksi t {w} ORDER BY t.tanggal, t.id", args)
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["Tanggal", "Jenis", "Kategori", "Keterangan", "Nominal"])
    for r in rows:
        wr.writerow([r["tanggal"], r["tipe"], _csv_safe(r["kategori"]), _csv_safe(r["keterangan"]), r["nominal"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=laporan-keuangan-rt.csv"})


# ---------------------------------------------------------------- tagihan (bendahara/ketua)
def _lunas(t, metode, oleh):
    """Tandai lunas + catat pemasukan kas, atomik dalam satu transaksi database."""
    d = db()
    d.execute("UPDATE tagihan SET status='lunas', metode=?, tgl_bayar=date('now','localtime'), verified_by=?, catatan=NULL WHERE id=?",
              (metode, oleh, t["id"]))
    d.execute("INSERT INTO transaksi(tipe,kategori,nominal,keterangan,tanggal,tagihan_id,created_by) "
              "VALUES('pemasukan','Iuran Warga',?,?,date('now','localtime'),?,?)",
              (t["nominal"], f"{t['jenis']} {t['periode']} - {t['nama']}", t["id"], oleh))
    d.commit()


@tagihan_bp.route("/tagihan")
@roles_required("ketua", "bendahara")
def index():
    periode = _bulan_arg("periode") or date.today().strftime("%Y-%m")
    status = request.args.get("status", "")
    where, args = ["t.periode=?"], [periode]
    if status in STATUS["tagihan"]:
        where.append("t.status=?")
        args.append(status)
    rows = q("SELECT t.*, w.nama, w.alamat FROM tagihan t JOIN warga w ON w.id=t.warga_id "
             f"WHERE {' AND '.join(where)} ORDER BY w.nama", args)
    tot = q("SELECT COALESCE(SUM(nominal),0) total, COALESCE(SUM(CASE WHEN status='lunas' THEN nominal END),0) lunas "
            "FROM tagihan WHERE periode=?", (periode,), one=True)
    return render_template("keuangan/tagihan.html", rows=rows, periode=periode, status=status, tot=tot,
                           iuran=get_settings().get("iuran_bulanan", "50000"))


@tagihan_bp.post("/tagihan/generate")
@roles_required("bendahara")
def generate():
    periode = text("periode", "Periode", 7, pattern=r"\d{4}-(0[1-9]|1[0-2])")
    jenis = text("jenis", "Jenis tagihan", 60)
    nominal = num("nominal", "Nominal", 1000, 10 ** 8)
    cur = db().execute("INSERT OR IGNORE INTO tagihan(warga_id,periode,jenis,nominal) "
                       "SELECT id,?,?,? FROM warga WHERE aktif=1", (periode, jenis, nominal))
    n = cur.rowcount
    db().commit()
    log("tagihan_generate", f"{periode} {jenis} x{n}")
    if n:
        akun = [r["user_id"] for r in q("SELECT user_id FROM warga WHERE aktif=1 AND user_id IS NOT NULL")]
        notify(akun, "Tagihan baru", f"{jenis} {periode}: Rp {nominal:,}".replace(",", "."), url_for("tagihan.saya"))
    flash(f"{n} tagihan dibuat." if n else "Tagihan untuk periode & jenis ini sudah ada.", "ok" if n else "error")
    return redirect(url_for("tagihan.index", periode=periode))


@tagihan_bp.post("/tagihan/<int:tid>/aksi")
@roles_required("bendahara")
def aksi(tid):
    t = q("SELECT t.*, w.nama FROM tagihan t JOIN warga w ON w.id=t.warga_id WHERE t.id=?", (tid,), one=True)
    if not t:
        abort(404)
    act, u = request.form.get("aksi", ""), current_user()
    wuser, link = user_of_warga(t["warga_id"]), url_for("tagihan.saya")
    if act == "terima" and t["status"] == "menunggu_verifikasi":
        _lunas(t, t["metode"] or "Transfer", u["id"])
        notify([wuser], "Pembayaran diverifikasi", f"{t['jenis']} {t['periode']} lunas. Terima kasih!", link)
    elif act == "tunai" and t["status"] in ("belum_bayar", "ditolak"):
        _lunas(t, "Tunai", u["id"])
        notify([wuser], "Pembayaran tunai dicatat", f"{t['jenis']} {t['periode']} lunas.", link)
    elif act == "tolak" and t["status"] == "menunggu_verifikasi":
        alasan = text("catatan", "Alasan penolakan", 200)
        db().execute("UPDATE tagihan SET status='ditolak', catatan=?, verified_by=? WHERE id=?", (alasan, u["id"], tid))
        db().commit()
        notify([wuser], "Bukti pembayaran ditolak", alasan, link)
    else:
        raise Invalid("Aksi tidak valid untuk status tagihan saat ini.")
    log(f"tagihan_{act}", f"#{tid}")
    flash("Tagihan diperbarui.", "ok")
    return redirect(request.referrer and url_for("tagihan.index", periode=t["periode"]) or url_for("tagihan.index"))


# ---------------------------------------------------------------- tagihan saya (warga)
@tagihan_bp.route("/tagihan-saya")
@roles_required("warga")
def saya():
    wid = my_warga_id() or 0
    rows = q("SELECT * FROM tagihan WHERE warga_id=? ORDER BY periode DESC, id DESC", (wid,))
    tunggak = sum(r["nominal"] for r in rows if r["status"] in ("belum_bayar", "ditolak"))
    return render_template("keuangan/tagihan_saya.html", rows=rows, tunggak=tunggak, metode=METODE_PILIHAN,
                           info=get_settings().get("info_pembayaran", ""))


@tagihan_bp.post("/tagihan-saya/<int:tid>/bayar")
@roles_required("warga")
def bayar(tid):
    t = q("SELECT * FROM tagihan WHERE id=? AND warga_id=?", (tid, my_warga_id() or 0), one=True)
    if not t:
        abort(404)
    if t["status"] not in ("belum_bayar", "ditolak"):
        raise Invalid("Tagihan ini tidak dapat dibayar lagi.")
    metode = choice("metode", "metode pembayaran", METODE)
    if metode == "QRIS":
        metode = "QR Dana"
    elif metode == "Transfer Bank":
        metode = "Transfer Bank BCA"
    bukti = save_image("bukti", required=True)
    db().execute("UPDATE tagihan SET status='menunggu_verifikasi', bukti=?, metode=?, catatan=NULL WHERE id=?", (bukti, metode, tid))
    db().commit()
    log("tagihan_bayar", f"#{tid}")
    notify(users_by_role("bendahara"), "Bukti pembayaran masuk", f"{t['jenis']} {t['periode']}", url_for("tagihan.index", periode=t["periode"]))
    flash("Bukti pembayaran terkirim. Menunggu verifikasi Bendahara.", "ok")
    return redirect(url_for("tagihan.saya"))


# ---------------------------------------------------------------- transparansi kas (read-only, semua peran non-admin)
@transparan_bp.route("/transparansi")
@roles_required("warga", "sekretaris", "humas", "ketua", "bendahara")
def transparansi():
    """Laporan pemasukan & pengeluaran kas RT untuk dilihat warga. Hanya membaca; nama pembayar iuran disamarkan."""
    bulan, tipe = _bulan_arg(), request.args.get("tipe", "")
    where, args = [], []
    if bulan:
        where.append("substr(t.tanggal,1,7)=?")
        args.append(bulan)
    if tipe in ("pemasukan", "pengeluaran"):
        where.append("t.tipe=?")
        args.append(tipe)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = q(ui.SQL_TRANSAKSI_PUBLIK + f" {w} ORDER BY t.tanggal DESC, t.id DESC LIMIT 300", args)

    # ringkasan periode terpilih (semua bulan bila filter bulan kosong)
    wb, ab = ("WHERE substr(tanggal,1,7)=?", (bulan,)) if bulan else ("", ())
    masuk = scalar(f"SELECT COALESCE(SUM(nominal),0) FROM transaksi {wb}{' AND' if wb else 'WHERE'} tipe='pemasukan'", ab)
    keluar = scalar(f"SELECT COALESCE(SUM(nominal),0) FROM transaksi {wb}{' AND' if wb else 'WHERE'} tipe='pengeluaran'", ab)
    dist = lambda t: q(f"SELECT kategori, SUM(nominal) total FROM transaksi {wb}{' AND' if wb else 'WHERE'} tipe='{t}' "
                       "GROUP BY kategori ORDER BY total DESC", ab)
    return render_template("keuangan/transparansi.html", rows=rows, bulan=bulan, tipe=tipe, masuk=masuk, keluar=keluar,
                           saldo=saldo(), grafik=ui.grafik_kas(), dist_masuk=dist("pemasukan"), dist_keluar=dist("pengeluaran"),
                           bulan_list=ui.bulan_tersedia(), info=get_settings().get("info_pembayaran", ""))
