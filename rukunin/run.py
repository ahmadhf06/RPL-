"""Titik masuk aplikasi.  Jalankan:  python run.py  (atau tombol Run di VS Code)"""
import os
import subprocess
import sys


def pastikan_modul():
    """Pasang modul yang kurang secara otomatis ke Python yang sedang dipakai."""
    try:
        import flask  # noqa: F401
        import segno  # noqa: F401
        import pymupdf  # noqa: F401  (unggah tanda tangan berbentuk PDF)
    except ImportError:
        req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        print("Memasang modul yang dibutuhkan (hanya sekali, butuh internet)...")
        r = subprocess.call([sys.executable, "-m", "pip", "install", "-r", req])
        if r != 0:
            print("\nGAGAL memasang modul. Jalankan manual:\n  \"%s\" -m pip install -r requirements.txt" % sys.executable)
            sys.exit(1)


pastikan_modul()
from smartrt import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    import threading
    import webbrowser

    port = int(os.environ.get("PORT", 5000))
    url = "http://localhost:%d" % port
    print("\n>>> Buka di browser: %s  <<<\n" % url)

    # Buka browser sekali saja (bukan di proses reloader mode debug)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
