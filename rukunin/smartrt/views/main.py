"""Login/logout, dashboard per peran, notifikasi, profil, dan API JSON."""
import os
import re
import uuid
from datetime import date

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash

from ..core import (ROLES, hash_pw, STATUS, Invalid, can_see_laporan, csrf_token, current_user, ex, log, login_fail,
                    login_locked, login_required, login_reset, monthly, my_warga_id, q, roles_required, rupiah, safe_back, safe_next,
                    save_image, saldo, scalar, text, validate_password)
from .. import ui

bp = Blueprint("main", __name__)
_DUMMY = hash_pw("dummy-password-1")      # menyamakan waktu respons login


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()[:50]
        pw = request.form.get("password") or ""
        key = (request.remote_addr, username)
        if login_locked(key):
            flash("Terlalu banyak percobaan gagal. Coba lagi dalam 5 menit.", "error")
        else:
            u = q("SELECT * FROM users WHERE username=?", (username,), one=True)
            pw_benar = check_password_hash(u["password_hash"] if u else _DUMMY, pw) and u
            ok = pw_benar and u["aktif"]
            if pw_benar and not u["aktif"]:
                # Kata sandi benar tetapi akun belum aktif: beri tahu pemilik akun statusnya (bukan ke orang lain).
                daftar = q("SELECT status, catatan FROM pendaftaran WHERE user_id=? ORDER BY id DESC", (u["id"],), one=True)
                if daftar and daftar["status"] == "menunggu":
                    flash("Pendaftaran Anda masih menunggu verifikasi Ketua RT. Anda dapat masuk setelah disetujui.", "ok")
                elif daftar and daftar["status"] == "ditolak":
                    flash(f"Pendaftaran Anda ditolak: {daftar['catatan'] or '-'}. Silakan daftar ulang dengan data yang benar.", "error")
                else:
                    flash("Akun Anda nonaktif. Hubungi Ketua RT atau Admin.", "error")
                return render_template("main/login.html")
            if ok:
                login_reset(key)
                session.clear()                       # cegah session fixation
                session["uid"] = u["id"]
                session.permanent = True
                csrf_token()
                ex("UPDATE users SET last_login=datetime('now','localtime') WHERE id=?", (u["id"],))
                log("login", username)
                return redirect(safe_next(request.args.get("next"), url_for("main.dashboard")))
            login_fail(key)
            log("login_gagal", username)
            flash("Username atau kata sandi salah, atau akun nonaktif.", "error")
    return render_template("main/login.html")


@bp.post("/logout")
@login_required
def logout():
    log("logout")
    session.clear()
    flash("Anda telah keluar.", "ok")
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------- dashboard
def _by_status(table, kind, where="", args=()):
    got = {r["k"]: r["n"] for r in q(f"SELECT status k, COUNT(*) n FROM {table} {where} GROUP BY status", args)}
    return [(lbl, got.get(k, 0)) for k, (lbl, _) in STATUS[kind].items()]


def stats_for(u):
    """Kartu & grafik dashboard sesuai peran. Dipakai halaman dashboard dan /api/stats."""
    role, uid = u["role"], u["id"]
    today, bulan = date.today().isoformat(), date.today().strftime("%Y-%m")
    cards, charts = [], []

    def card(key, label, value, icon, link=None, sub="", trend=None, progress=None):
        """sub = teks kecil di bawah angka; trend = 'up'/'down'; progress = 0-100 (bilah di bawah angka)."""
        cards.append(dict(key=key, label=label, value=str(value), icon=icon, link=link, sub=sub, trend=trend,
                          progress=progress))

    def kartu_warga():
        baru = cnt("SELECT COUNT(*) FROM warga WHERE aktif=1 AND substr(created_at,1,7)=?", (bulan,))
        card("warga", "Total Warga", cnt("SELECT COUNT(*) FROM warga WHERE aktif=1"), "users", url_for("warga.index"),
             sub=f"+{baru} bulan ini" if baru else "warga aktif", trend="up" if baru else None)

    def kartu_kas():
        masuk = cnt("SELECT SUM(nominal) FROM transaksi WHERE tipe='pemasukan' AND substr(tanggal,1,7)=?", (bulan,))
        keluar = cnt("SELECT SUM(nominal) FROM transaksi WHERE tipe='pengeluaran' AND substr(tanggal,1,7)=?", (bulan,))
        net, sekarang = masuk - keluar, saldo()
        awal = sekarang - net
        if awal > 0 and net:
            pct = round(net * 100 / awal)
            sub, trend = f"{'+' if pct >= 0 else ''}{pct}% bulan ini", ("up" if pct >= 0 else "down")
        else:
            sub, trend = "saldo saat ini", None
        card("saldo", "Kas RT", rupiah(sekarang), "wallet", url_for("keuangan.index"), sub=sub, trend=trend)

    def kartu_iuran(link=None):
        per = scalar("SELECT MAX(periode) FROM tagihan")
        tot = cnt("SELECT COUNT(*) FROM tagihan WHERE periode=?", (per,)) if per else 0
        lunas = cnt("SELECT COUNT(*) FROM tagihan WHERE periode=? AND status='lunas'", (per,)) if per else 0
        pct = round(lunas * 100 / tot) if tot else 0
        card("iuran", "Iuran Terbayar", f"{pct}%", "receipt", link,
             sub=f"{lunas} dari {tot} tagihan · {ui.periode_label(per)}" if per else "belum ada tagihan", progress=pct)

    def cnt(sql, a=()):
        return scalar(sql, a) or 0

    if role == "admin":
        card("akun", "Akun aktif", cnt("SELECT COUNT(*) FROM users WHERE aktif=1"), "users", url_for("admin.akun"))
        card("nonaktif", "Akun nonaktif", cnt("SELECT COUNT(*) FROM users WHERE aktif=0"), "key", url_for("admin.akun"))
        card("login24", "Login 24 jam terakhir",
             cnt("SELECT COUNT(*) FROM users WHERE last_login>=datetime('now','localtime','-1 day')"), "user")
        card("aktivitas", "Aktivitas hari ini",
             cnt("SELECT COUNT(*) FROM activity_log WHERE date(created_at)=date('now','localtime')"), "list",
             url_for("admin.log_aktivitas"))
        got = {r["role"]: r["n"] for r in q("SELECT role, COUNT(*) n FROM users WHERE aktif=1 GROUP BY role")}
        charts.append(dict(title="Akun aktif per peran", items=[(ROLES[k], got.get(k, 0)) for k in ROLES]))
    elif role == "ketua":
        kartu_warga()
        kartu_kas()
        kartu_iuran(url_for("tagihan.index"))
        menunggu = cnt("SELECT COUNT(*) FROM surat WHERE status='menunggu_ketua'")
        card("surat", "Pengajuan Surat", cnt("SELECT COUNT(*) FROM surat WHERE status IN ('diajukan','menunggu_ketua')"),
             "file", url_for("surat.index"), sub=f"{menunggu} menunggu persetujuan Anda" if menunggu else "tidak ada yang menunggu Anda")
        daftar_baru = cnt("SELECT COUNT(*) FROM pendaftaran WHERE status='menunggu'")
        if daftar_baru:                              # kartu muncul hanya saat ada pendaftar yang perlu diverifikasi
            card("pendaftaran", "Pendaftaran Warga", daftar_baru, "user", url_for("pendaftaran.index"),
                 sub="menunggu verifikasi Anda")
        charts += [dict(title="Laporan per status", items=_by_status("laporan", "laporan")),
                   dict(title="Surat per status", items=_by_status("surat", "surat")),
                   dict(title="Pemasukan 6 bulan terakhir", items=monthly("pemasukan"), money=True),
                   dict(title="Pengeluaran 6 bulan terakhir", items=monthly("pengeluaran"), money=True)]
    elif role == "sekretaris":
        kartu_warga()
        card("periksa", "Pengajuan Surat", cnt("SELECT COUNT(*) FROM surat WHERE status='diajukan'"), "file",
             url_for("surat.index", status="diajukan"), sub="perlu diperiksa")
        card("ketua", "Menunggu Ketua RT", cnt("SELECT COUNT(*) FROM surat WHERE status='menunggu_ketua'"), "list",
             url_for("surat.index", status="menunggu_ketua"), sub="menunggu persetujuan")
        selesai = cnt("SELECT COUNT(*) FROM surat WHERE status='selesai' AND substr(updated_at,1,7)=?", (bulan,))
        card("arsip", "Siap Diarsipkan", cnt("SELECT COUNT(*) FROM surat WHERE status='disetujui'"), "check",
             url_for("surat.index", status="disetujui"), sub=f"{selesai} diarsipkan bulan ini")
        charts.append(dict(title="Surat per status", items=_by_status("surat", "surat")))
        charts.append(dict(title="Surat per jenis", items=[(r["jenis"], r["n"]) for r in q(
            "SELECT jenis, COUNT(*) n FROM surat GROUP BY jenis ORDER BY n DESC LIMIT 6")]))
    elif role == "bendahara":
        kartu_warga()
        kartu_kas()
        kartu_iuran(url_for("tagihan.index"))
        tunggak = cnt("SELECT COUNT(*) FROM tagihan WHERE status IN ('belum_bayar','ditolak')")
        card("verif", "Menunggu Verifikasi", cnt("SELECT COUNT(*) FROM tagihan WHERE status='menunggu_verifikasi'"),
             "check", url_for("tagihan.index", status="menunggu_verifikasi"), sub=f"{tunggak} tagihan belum dibayar")
        charts += [dict(title="Tagihan per status", items=_by_status("tagihan", "tagihan")),
                   dict(title="Pemasukan 6 bulan terakhir", items=monthly("pemasukan"), money=True),
                   dict(title="Pengeluaran 6 bulan terakhir", items=monthly("pengeluaran"), money=True)]
    elif role == "humas":
        aktif_p = cnt("SELECT COUNT(*) FROM pengumuman WHERE author_id=?", (uid,))
        card("pengumuman", "Pengumuman saya", aktif_p, "megaphone", url_for("komunitas.pengumuman"),
             sub=f"{cnt('SELECT COUNT(*) FROM pengumuman')} pengumuman di RT")
        baru_a = cnt("SELECT COUNT(*) FROM aspirasi WHERE status='baru'")
        card("aspirasi", "Aspirasi Baru", baru_a, "message", url_for("komunitas.aspirasi"),
             sub="perlu ditanggapi" if baru_a else "semua sudah ditanggapi")
        card("kegiatan", "Kegiatan Mendatang", cnt(
            "SELECT COUNT(*) FROM kegiatan WHERE aktif=1 AND tanggal>=?", (today,)), "calendar",
             url_for("komunitas.kegiatan"))
        card("voting", "Voting Berjalan", cnt(
            "SELECT COUNT(*) FROM voting WHERE status='aktif' AND berakhir>=?", (today,)), "vote",
             url_for("komunitas.voting"))
        charts.append(dict(title="Aspirasi per status", items=_by_status("aspirasi", "aspirasi")))
        charts.append(dict(title="Laporan per status", items=_by_status("laporan", "laporan")))
    else:  # warga
        wid = my_warga_id() or 0
        card("tunggakan", "Tagihan belum dibayar", rupiah(cnt(
            "SELECT SUM(nominal) FROM tagihan WHERE warga_id=? AND status IN ('belum_bayar','ditolak')", (wid,))),
             "receipt", url_for("tagihan.saya"))
        card("surat", "Surat berjalan", cnt(
            "SELECT COUNT(*) FROM surat WHERE warga_id=? AND status NOT IN ('selesai','ditolak')", (wid,)),
             "file", url_for("surat.index"))
        card("laporan", "Laporan saya berjalan", cnt(
            "SELECT COUNT(*) FROM laporan WHERE user_id=? AND status IN ('baru','diproses')", (uid,)),
             "alert", url_for("laporan.index"))
        card("voting", "Voting menunggu suara", cnt(
            "SELECT COUNT(*) FROM voting v WHERE v.status='aktif' AND v.berakhir>=? AND NOT EXISTS "
            "(SELECT 1 FROM voting_suara s WHERE s.voting_id=v.id AND s.user_id=?)", (today, uid)),
             "vote", url_for("komunitas.voting"))
        charts.append(dict(title="Status tagihan saya",
                           items=_by_status("tagihan", "tagihan", "WHERE warga_id=?", (wid,))))
    return cards, charts


@bp.route("/")
@login_required
def dashboard():
    u = current_user()
    cards, charts = stats_for(u)
    keuangan = u["role"] in ("ketua", "bendahara")
    return render_template(
        "main/dashboard.html", cards=cards, charts=charts,
        grafik=ui.grafik_kas() if keuangan else None,
        transparan=ui.ringkasan_transparan(5) if u["role"] in ("warga", "sekretaris", "humas") else None,
        jadwal=ui.jadwal(u),
        aktivitas=ui.aktivitas_terbaru(u, 4),
        laporan_baru=ui.laporan_terbaru(u, 3),
        pengumuman=q("SELECT * FROM pengumuman ORDER BY id DESC LIMIT 3"),
        ronda=q("SELECT r.tanggal, r.pos, w.nama, w.user_id FROM ronda r JOIN warga w ON w.id=r.warga_id "
                "WHERE r.tanggal>=date('now','localtime') ORDER BY r.tanggal, r.id LIMIT 5"))


@bp.get("/api/stats")
def api_stats():
    u = current_user()
    if not u:
        return jsonify(error="auth"), 401
    cards, _ = stats_for(u)
    return jsonify(cards={c["key"]: c["value"] for c in cards})


# ---------------------------------------------------------------- notifikasi
@bp.get("/api/notifikasi")
def api_notifikasi():
    u = current_user()
    if not u:
        return jsonify(error="auth"), 401
    rows = q("SELECT id,judul,pesan,link,dibaca,created_at FROM notifikasi WHERE user_id=? ORDER BY id DESC LIMIT 8",
             (u["id"],))
    unread = scalar("SELECT COUNT(*) FROM notifikasi WHERE user_id=? AND dibaca=0", (u["id"],))
    return jsonify(unread=unread, items=[dict(r) for r in rows])


@bp.route("/notifikasi")
@login_required
def notifikasi():
    rows = q("SELECT * FROM notifikasi WHERE user_id=? ORDER BY id DESC LIMIT 100", (current_user()["id"],))
    return render_template("main/notifikasi.html", rows=rows)


@bp.post("/notifikasi/baca-semua")
@login_required
def notifikasi_baca_semua():
    ex("UPDATE notifikasi SET dibaca=1 WHERE user_id=?", (current_user()["id"],))
    return redirect(url_for("main.notifikasi"))


@bp.get("/notifikasi/<int:nid>/buka")
@login_required
def notifikasi_buka(nid):
    n = q("SELECT * FROM notifikasi WHERE id=? AND user_id=?", (nid, current_user()["id"]), one=True)
    if not n:
        abort(404)
    ex("UPDATE notifikasi SET dibaca=1 WHERE id=?", (nid,))
    return redirect(safe_next(n["link"], url_for("main.notifikasi")))


# ---------------------------------------------------------------- profil
@bp.route("/profil", methods=["GET", "POST"])
@login_required
def profil():
    u = current_user()
    if request.method == "POST":
        if request.form.get("aksi") == "password":
            lama, baru = request.form.get("lama", ""), request.form.get("baru", "")
            if not check_password_hash(u["password_hash"], lama):
                raise Invalid("Kata sandi lama salah.")
            if baru != request.form.get("konfirmasi", ""):
                raise Invalid("Konfirmasi kata sandi tidak cocok.")
            validate_password(baru)
            ex("UPDATE users SET password_hash=? WHERE id=?", (hash_pw(baru), u["id"]))
            log("ganti_password")
            flash("Kata sandi berhasil diganti.", "ok")
        else:
            nama = text("nama", "Nama", 100)
            telp = text("telepon", "Telepon", 20, required=False, pattern=r"[0-9+\- ]{8,20}")
            ex("UPDATE users SET nama=? WHERE id=?", (nama, u["id"]))
            if u["role"] == "warga":
                ex("UPDATE warga SET telepon=? WHERE user_id=?", (telp, u["id"]))
            flash("Profil diperbarui.", "ok")
        return redirect(url_for("main.profil"))
    w = q("SELECT * FROM warga WHERE user_id=?", (u["id"],), one=True)
    return render_template("main/profil.html", w=w)


# ---------------------------------------------------------------- foto profil
def _hapus_berkas_foto(name):
    if name and re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", name):
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        except OSError:
            pass


@bp.post("/profil/foto")
@login_required
def profil_foto():
    """Unggah / hapus foto profil sendiri. Permintaan dari JavaScript (header X-Requested-With: fetch) dibalas JSON."""
    u = current_user()
    ajax = request.headers.get("X-Requested-With") == "fetch"
    try:
        if request.form.get("hapus"):
            ex("UPDATE users SET foto=NULL WHERE id=?", (u["id"],))
            _hapus_berkas_foto(u["foto"])
            log("hapus_foto_profil")
            pesan = "Foto profil dihapus."
            url = url_for("static", filename="img/avatar-default.svg")
        else:
            name = save_image("foto", required=True, label="Foto profil", max_mb=5)
            ex("UPDATE users SET foto=? WHERE id=?", (name, u["id"]))
            _hapus_berkas_foto(u["foto"])
            log("ganti_foto_profil")
            pesan = "Foto profil diperbarui."
            url = url_for("main.avatar", name=name)
    except Invalid as e:
        if ajax:
            return jsonify(ok=False, pesan=str(e)), 400
        raise
    if ajax:
        return jsonify(ok=True, pesan=pesan, url=url)
    flash(pesan, "ok")
    return redirect(safe_back(url_for("main.profil")))


def _ttd_dari_pdf(f):
    """PDF tanda tangan -> PNG: hanya halaman pertama, area kosong di sekeliling goresan dibuang, latar transparan."""
    f.stream.seek(0, os.SEEK_END)
    if f.stream.tell() > 2 * 1024 * 1024:
        raise Invalid("Berkas PDF terlalu besar (maksimal 2 MB).")
    f.stream.seek(0)
    data = f.stream.read()
    try:
        import pymupdf
    except ImportError:
        raise Invalid("Dukungan PDF belum terpasang di server (jalankan: pip install pymupdf). Untuk sementara unggah gambar JPG/PNG.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.needs_pass or doc.page_count < 1:
            raise ValueError("pdf terkunci/kosong")
        page = doc[0]
        box = None
        for _, r in page.get_bboxlog():
            r = pymupdf.Rect(r)
            if r.is_empty or r.is_infinite:
                continue
            box = r if box is None else box | r
        if box is None:
            raise ValueError("halaman kosong")
        box = pymupdf.Rect(box.x0 - 6, box.y0 - 6, box.x1 + 6, box.y1 + 6) & page.rect
        zoom = max(1.0, min(4.0, 900 / max(box.width, 1)))
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=box, alpha=True).tobytes("png")
    except Exception:
        raise Invalid("PDF tidak dapat dibaca atau dikunci kata sandi. Gunakan PDF biasa yang berisi tanda tangan, atau unggah gambar.")
    name = f"{uuid.uuid4().hex}.png"
    with open(os.path.join(current_app.config["UPLOAD_FOLDER"], name), "wb") as out:
        out.write(png)
    return name


@bp.post("/profil/ttd")
@roles_required("ketua")
def profil_ttd():
    """Ketua RT mengunggah / menghapus gambar tanda tangan; ikut tercetak pada surat yang ia setujui sesudahnya."""
    u = current_user()
    if request.form.get("hapus"):
        baru, pesan = None, "Gambar tanda tangan dihapus."
    else:
        up = request.files.get("ttd")
        pdf = False
        if up and up.filename:
            pdf = up.stream.read(5) == b"%PDF-"
            up.stream.seek(0)
        baru = _ttd_dari_pdf(up) if pdf else save_image("ttd", required=True, label="Gambar tanda tangan", max_mb=2)
        pesan = "Gambar tanda tangan disimpan. Akan dipakai pada surat yang Anda setujui berikutnya."
    ex("UPDATE users SET ttd_gambar=? WHERE id=?", (baru, u["id"]))
    lama = u["ttd_gambar"]
    if lama and lama != baru and not scalar("SELECT 1 FROM surat WHERE ttd_gambar=?", (lama,)):   # berkas yang masih dipakai surat lama dipertahankan
        _hapus_berkas_foto(lama)
    log("ttd_ganti" if baru else "ttd_hapus")
    flash(pesan, "ok")
    return redirect(url_for("main.profil"))


@bp.get("/avatar/<name>")
@login_required
def avatar(name):
    """Foto profil pengguna (boleh dilihat semua pengguna yang login)."""
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", name) or not scalar("SELECT 1 FROM users WHERE foto=?", (name,)):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name)


# ---------------------------------------------------------------- berkas unggahan (dijaga RBAC)
@bp.get("/media/<name>")
@login_required
def media(name):
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", name):
        abort(404)
    u = current_user()
    lap = q("SELECT * FROM laporan WHERE foto=?", (name,), one=True)
    if lap:
        if not can_see_laporan(u, lap):
            abort(403)
    elif scalar("SELECT 1 FROM pendaftaran WHERE foto_ktp=? OR foto_kk=?", (name, name)):
        if u["role"] != "ketua":                     # KTP/KK calon warga: hanya Ketua RT
            abort(403)
    elif scalar("SELECT 1 FROM users WHERE ttd_gambar=?", (name,)) or scalar("SELECT 1 FROM surat WHERE ttd_gambar=?", (name,)):
        # gambar tanda tangan: Ketua/Sekretaris, atau warga pemilik surat yang bersangkutan
        punya = scalar("SELECT 1 FROM surat s JOIN warga w ON w.id=s.warga_id WHERE s.ttd_gambar=? AND w.user_id=?", (name, u["id"]))
        if not (u["role"] in ("ketua", "sekretaris") or punya):
            abort(403)
    else:
        t = q("SELECT w.user_id FROM tagihan t JOIN warga w ON w.id=t.warga_id WHERE t.bukti=?", (name,), one=True)
        if not t:
            abort(404)
        if u["role"] not in ("bendahara", "ketua") and t["user_id"] != u["id"]:
            abort(403)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name)
