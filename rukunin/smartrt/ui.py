"""Data untuk tampilan: aksi cepat, aktivitas terbaru, laporan terbaru, jadwal, grafik kas, info panel kanan.

Semua fungsi hanya MEMBACA database (tidak mengubah apa pun) dan memakai hak akses yang sama dengan halaman aslinya.
"""
from datetime import date

from flask import current_app, url_for

from .core import STATUS, bulan_label, get_settings, monthly, q, scalar, my_warga_id


# ---------------------------------------------------------------- aksi cepat (panel kanan)
def aksi_cepat(u):
    def a(label, icon, ep, danger=False, **kw):
        return dict(label=label, icon=icon, url=url_for(ep, **kw), danger=danger)

    r = u["role"]
    if r == "warga":
        return [a("Buat Surat", "file", "surat.baru"), a("Bayar Iuran", "wallet", "tagihan.saya"),
                a("Lapor Lingkungan", "alert", "laporan.baru"), a("Alarm Darurat", "siren", "darurat.panel", True)]
    if r == "ketua":
        return [a("Surat Masuk", "file", "surat.index"), a("Cek Saldo Kas", "coins", "keuangan.index"),
                a("Lapor Lingkungan", "alert", "laporan.index"), a("Alarm Darurat", "siren", "darurat.panel", True)]
    if r == "sekretaris":
        return [a("Kelola Surat", "file", "surat.index"), a("Pengumuman", "megaphone", "komunitas.pengumuman"),
                a("Lapor Lingkungan", "alert", "laporan.index"), a("Alarm Darurat", "siren", "darurat.panel", True)]
    if r == "bendahara":
        return [a("Tagihan Iuran", "wallet", "tagihan.index"), a("Catat Kas", "coins", "keuangan.index"),
                a("Lapor Lingkungan", "alert", "laporan.index"), a("Alarm Darurat", "siren", "darurat.panel", True)]
    if r == "humas":
        return [a("Buat Pengumuman", "megaphone", "komunitas.pengumuman"), a("Aspirasi Warga", "message", "komunitas.aspirasi"),
                a("Jadwalkan Kegiatan", "qr", "komunitas.kegiatan"), a("Alarm Darurat", "siren", "darurat.panel", True)]
    return [a("Kelola Akun", "key", "admin.akun"), a("Pengaturan", "cog", "admin.pengaturan"),
            a("Log Aktivitas", "list", "admin.log_aktivitas"), a("Pengumuman", "megaphone", "komunitas.pengumuman")]


def panel_info(u):
    """Data panel profil kanan (tampil di semua halaman)."""
    cfg = get_settings()
    cfgapp = current_app.config
    try:
        lat = float(cfg.get("lat") or cfgapp["WEATHER_LAT"])
        lng = float(cfg.get("lng") or cfgapp["WEATHER_LNG"])
    except (TypeError, ValueError):
        lat, lng = cfgapp["WEATHER_LAT"], cfgapp["WEATHER_LNG"]
    lokasi = ", ".join(x for x in (cfg.get("kelurahan"), cfg.get("kota")) if x)
    return dict(
        aksi=aksi_cepat(u),
        alarm=bool(scalar("SELECT COUNT(*) FROM alarm_darurat WHERE status='aktif'")),
        alarm_id=scalar("SELECT id FROM alarm_darurat WHERE status='aktif' ORDER BY id DESC LIMIT 1") or 0,
        lat=lat, lng=lng, lokasi=lokasi,
        telepon=scalar("SELECT telepon FROM warga WHERE user_id=?", (u["id"],)) if u["role"] == "warga" else None,
    )


# ---------------------------------------------------------------- laporan & aktivitas
def _where_laporan(u):
    if u["role"] == "warga":
        return "WHERE l.user_id=?", (u["id"],)
    if u["role"] == "ketua":
        return "", ()
    return "WHERE l.pj_id=?", (u["id"],)          # sekretaris/bendahara: hanya yang ditugaskan


def laporan_terbaru(u, limit=3):
    if u["role"] == "admin":
        return []
    w, args = _where_laporan(u)
    rows = q("SELECT l.id, l.judul, l.kategori, l.lokasi, l.status, l.created_at, p.nama AS pelapor "
             f"FROM laporan l JOIN users p ON p.id=l.user_id {w} ORDER BY l.id DESC LIMIT {int(limit)}", args)
    out = []
    for r in rows:
        label, warna = STATUS["laporan"].get(r["status"], (r["status"], "gray"))
        out.append(dict(id=r["id"], judul=r["judul"], kategori=r["kategori"], lokasi=r["lokasi"], pelapor=r["pelapor"],
                        ts=r["created_at"], badge=(label, warna), url=url_for("laporan.detail", lid=r["id"])))
    return out


def aktivitas_terbaru(u, limit=4):
    role, items = u["role"], []

    def add(ts, icon, title, meta, badge=None, link=None):
        items.append(dict(ts=str(ts or ""), icon=icon, title=title, meta=meta, badge=badge, link=link))

    for p in q("SELECT judul, created_at, penting FROM pengumuman ORDER BY id DESC LIMIT 3"):
        add(p["created_at"], "megaphone", p["judul"], "Pengumuman RT",
            ("Penting", "amber") if p["penting"] else ("Info", "emerald"), url_for("komunitas.pengumuman"))

    if role == "admin":
        for a in q("SELECT a.aksi, a.detail, a.created_at, u.nama FROM activity_log a "
                   "LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 4"):
            add(a["created_at"], "list", a["aksi"].replace("_", " ").capitalize(),
                "oleh " + (a["nama"] or "sistem"), None, url_for("admin.log_aktivitas"))
    else:
        wid = my_warga_id() or 0
        if role in ("warga", "sekretaris", "ketua"):
            where, args = ("WHERE s.warga_id=?", (wid,)) if role == "warga" else ("", ())
            for s in q("SELECT s.id, s.jenis, s.status, s.updated_at, w.nama FROM surat s JOIN warga w ON w.id=s.warga_id "
                       f"{where} ORDER BY s.updated_at DESC LIMIT 3", args):
                add(s["updated_at"], "file", f"Pengajuan {s['jenis']}", "oleh " + s["nama"],
                    STATUS["surat"].get(s["status"]), url_for("surat.detail", sid=s["id"]))
        if role in ("warga", "ketua", "bendahara"):
            where, args = ("AND t.warga_id=?", (wid,)) if role == "warga" else ("", ())
            for t in q("SELECT t.jenis, t.periode, t.status, COALESCE(t.tgl_bayar, t.created_at) AS ts, w.nama "
                       "FROM tagihan t JOIN warga w ON w.id=t.warga_id "
                       f"WHERE t.status IN ('lunas','menunggu_verifikasi') {where} ORDER BY ts DESC LIMIT 3", args):
                add(t["ts"], "wallet", f"Pembayaran {t['jenis'].lower()} {t['periode']}", "oleh " + t["nama"],
                    STATUS["tagihan"].get(t["status"]),
                    url_for("tagihan.saya" if role == "warga" else "tagihan.index"))
        if role in ("humas", "ketua"):
            for a in q("SELECT a.judul, a.status, a.created_at, u.nama FROM aspirasi a JOIN users u ON u.id=a.user_id "
                       "ORDER BY a.id DESC LIMIT 3"):
                add(a["created_at"], "message", "Aspirasi: " + a["judul"], "oleh " + a["nama"],
                    STATUS["aspirasi"].get(a["status"]), url_for("komunitas.aspirasi"))
        for l in laporan_terbaru(u, 3):
            add(l["ts"], "alert", "Laporan lingkungan: " + l["judul"], "oleh " + l["pelapor"], l["badge"], l["url"])

    items.sort(key=lambda i: i["ts"], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------- jadwal musyawarah / kegiatan
def jadwal(u, limit=2):
    rows = q("SELECT id, nama, jenis, tanggal, lokasi FROM kegiatan WHERE aktif=1 AND tanggal>=date('now','localtime') "
             f"ORDER BY tanggal, id LIMIT {int(limit)}")
    voting = scalar("SELECT COUNT(*) FROM voting WHERE status='aktif' AND berakhir>=?", (date.today().isoformat(),)) or 0
    return dict(kegiatan=[dict(r) for r in rows], voting=voting)


# ---------------------------------------------------------------- grafik kas (SVG, dihitung di server)
def _smooth(pts):
    """Kurva halus monoton (Fritsch–Carlson) lewat titik-titik: tidak melampaui nilai data, jadi tidak turun di bawah 0."""
    n = len(pts)
    if n < 2:
        return ""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    sl = [(ys[i + 1] - ys[i]) / dx[i] for i in range(n - 1)]
    m = [sl[0]] + [0 if sl[i - 1] * sl[i] <= 0 else (sl[i - 1] + sl[i]) / 2 for i in range(1, n - 1)] + [sl[-1]]
    for i in range(n - 1):
        if sl[i] == 0:
            m[i] = m[i + 1] = 0
            continue
        a, b = m[i] / sl[i], m[i + 1] / sl[i]
        h = (a * a + b * b) ** 0.5
        if h > 3:
            m[i], m[i + 1] = 3 * a * sl[i] / h, 3 * b * sl[i] / h
    d = f"M{xs[0]:.1f} {ys[0]:.1f}"
    for i in range(n - 1):
        d += (f" C{xs[i] + dx[i] / 3:.1f} {ys[i] + m[i] * dx[i] / 3:.1f}"
              f" {xs[i + 1] - dx[i] / 3:.1f} {ys[i + 1] - m[i + 1] * dx[i] / 3:.1f} {xs[i + 1]:.1f} {ys[i + 1]:.1f}")
    return d


def _tick(v):
    if v == 0:
        return "0"
    if v >= 1_000_000:
        return f"{v / 1_000_000:g} jt"
    return f"{v / 1_000:g} rb"


def grafik_kas():
    """Pemasukan vs pengeluaran 6 bulan terakhir -> data siap gambar untuk <svg viewBox='0 0 560 210'>."""
    masuk, keluar = monthly("pemasukan"), monthly("pengeluaran")
    mx = max([v for _, v in masuk] + [v for _, v in keluar] + [1])
    step = next((s for s in (1e5, 2e5, 5e5, 1e6, 2e6, 5e6, 1e7, 2e7, 5e7, 1e8, 2e8, 5e8, 1e9) if mx <= s * 3), 1e9)
    left, right, top, bottom = 50, 546, 14, 172
    pw, ph, n = right - left, bottom - top, len(masuk)

    def xy(i, v):
        return left + i * pw / (n - 1), bottom - min(v / (step * 3), 1) * ph

    def seri(data):
        pts = [xy(i, v) for i, (_, v) in enumerate(data)]
        line = _smooth(pts)
        area = f"{line} L{pts[-1][0]:.1f} {bottom} L{pts[0][0]:.1f} {bottom} Z"
        return dict(line=line, area=area, pts=[dict(x=round(x, 1), y=round(y, 1), v=data[i][1]) for i, (x, y) in enumerate(pts)])

    return dict(
        ticks=[dict(y=round(bottom - k * ph / 3, 1), label=_tick(int(step * k))) for k in range(4)],
        xlabels=[dict(x=round(xy(i, 0)[0], 1), label=m.split(" ")[0]) for i, (m, _) in enumerate(masuk)],
        masuk=seri(masuk), keluar=seri(keluar), left=left, right=right, bottom=bottom,
    )


def periode_label(p):
    try:
        return bulan_label(p)
    except Exception:
        return p


# ---------------------------------------------------------------- transparansi kas (untuk warga)
# Nama pembayar iuran TIDAK ditampilkan ke warga lain: transaksi dari tagihan hanya memuat jenis & periode.
SQL_TRANSAKSI_PUBLIK = (
    "SELECT t.id, t.tipe, t.kategori, t.nominal, t.tanggal, "
    "CASE WHEN t.tagihan_id IS NOT NULL THEN COALESCE(g.jenis || ' ' || g.periode, t.kategori) "
    "ELSE COALESCE(t.keterangan, '') END AS keterangan "
    "FROM transaksi t LEFT JOIN tagihan g ON g.id=t.tagihan_id")


def bulan_tersedia():
    """Daftar bulan (YYYY-MM) yang punya transaksi, terbaru dulu, untuk pilihan filter."""
    return [r["m"] for r in q("SELECT DISTINCT substr(tanggal,1,7) m FROM transaksi ORDER BY m DESC LIMIT 36")]


def ringkasan_transparan(limit=5):
    """Ringkasan kas untuk kartu dashboard warga: saldo, total bulan ini, dan transaksi terbaru."""
    bulan = date.today().strftime("%Y-%m")
    tot = lambda t: scalar("SELECT COALESCE(SUM(nominal),0) FROM transaksi WHERE tipe=? AND substr(tanggal,1,7)=?", (t, bulan))
    saldo_now = scalar("SELECT COALESCE(SUM(CASE tipe WHEN 'pemasukan' THEN nominal ELSE -nominal END),0) FROM transaksi")
    terbaru = q(SQL_TRANSAKSI_PUBLIK + f" ORDER BY t.tanggal DESC, t.id DESC LIMIT {int(limit)}")
    return dict(saldo=saldo_now, masuk=tot("pemasukan"), keluar=tot("pengeluaran"),
                bulan=bulan_label(bulan), terbaru=[dict(r) for r in terbaru])
