import os
import secrets
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE = os.path.join(ROOT, "instance")
os.makedirs(INSTANCE, exist_ok=True)


def _secret_key():
    """SECRET_KEY dari env, atau dibuat sekali dan disimpan di instance/secret.key."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(INSTANCE, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    with open(path) as f:
        return f.read().strip()


def _telegram_token():
    """Token bot Telegram dari env TELEGRAM_BOT_TOKEN, atau dari berkas instance/telegram_token.txt (satu baris)."""
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return os.environ["TELEGRAM_BOT_TOKEN"].strip()
    path = os.path.join(INSTANCE, "telegram_token.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            return f.read().strip()
    return ""


class Config:
    SECRET_KEY = _secret_key()
    DATABASE = os.environ.get("DATABASE", os.path.join(INSTANCE, "smartrt.db"))
    UPLOAD_FOLDER = os.path.join(INSTANCE, "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024           # batas satu permintaan 10 MB (pendaftaran: KTP + KK, maks. 4 MB per berkas)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE") == "1"   # set 1 bila memakai HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(hours=4)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "")          # mis. http://192.168.1.10:5000
    ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "1") == "1"   # 0 = tutup halaman /daftar
    # Koordinat untuk kartu cuaca di panel kanan (bisa juga diisi lewat Pengaturan: kunci "lat" dan "lng")
    WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "-6.2088"))
    WEATHER_LNG = float(os.environ.get("WEATHER_LNG", "106.8456"))

    # Bot Telegram untuk alarm darurat (lihat smartrt/telegram_bot.py dan README bagian "Bot Telegram")
    TELEGRAM_BOT_TOKEN = _telegram_token()
    TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "")        # Chat ID penerima alarm, pisahkan koma (bisa juga lewat Pengaturan Sistem)
    TELEGRAM_MODE = os.environ.get("TELEGRAM_MODE", "polling")         # polling (tanpa ngrok) | webhook | off
    TELEGRAM_WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "")  # alamat https publik, hanya untuk mode webhook
    TELEGRAM_ASYNC = True                                              # kirim ke Telegram di thread terpisah (False hanya untuk uji)
    # Alarm yang berbunyi otomatis di HP lewat aplikasi ntfy (lihat smartrt/ntfy_push.py dan README bagian "Alarm berbunyi di HP")
    NTFY_MODE = os.environ.get("NTFY_MODE", "on")                      # on | off
    NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")                      # kosong = dibuat acak otomatis dan disimpan di instance/ntfy_topic.txt
    NTFY_TOPIC_FILE = os.path.join(INSTANCE, "ntfy_topic.txt")
    NTFY_ASYNC = True                                                  # kirim di thread terpisah (False hanya untuk uji)
