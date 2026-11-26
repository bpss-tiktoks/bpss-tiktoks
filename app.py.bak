import os
import uuid
import shutil
import yt_dlp
from flask import Flask, request, send_file

app = Flask(__name__)

BASE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES = os.path.join(BASE, "cookies.txt")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

VIDEO_FORMAT = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
AUDIO_FORMAT = "ba[ext=m4a]/ba/b"


def get_valid_cookies():
    if os.path.isfile(COOKIES) and os.path.getsize(COOKIES) > 100:
        return COOKIES
    return None


def descargar_yt(url: str, es_audio: bool = False) -> str:
    job_id = str(uuid.uuid4())[:8]
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{job_id}_%(title).60s.%(ext)s")
    ffmpeg_ok = shutil.which("ffmpeg") is not None

    selector = AUDIO_FORMAT if es_audio else VIDEO_FORMAT

    ydl_opts = {
        "format": selector,
        "outtmpl": outtmpl,
        "noplaylist": True,
        "http_headers": {"User-Agent": UA},
        "nocheckcertificate": True,
    }

    cookiefile = get_valid_cookies()
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    if es_audio and ffmpeg_ok:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif not es_audio and ffmpeg_ok:
        ydl_opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = ydl.prepare_filename(info)

    base_sin_ext, _ = os.path.splitext(filepath)
    if es_audio and os.path.exists(base_sin_ext + ".mp3"):
        return base_sin_ext + ".mp3"
    if not es_audio and os.path.exists(base_sin_ext + ".mp4"):
        return base_sin_ext + ".mp4"
    return filepath


@app.route("/download", methods=["POST"])
def download():
    url = (request.form.get("url") or "").strip()
    tipo = (request.form.get("type") or request.form.get("format") or "video").strip().lower()

    if not url:
        return "Falta la URL", 400

    es_audio = tipo in ("audio", "mp3")

    try:
        archivo = descargar_yt(url, es_audio=es_audio)
        return send_file(archivo, as_attachment=True)
    except Exception as e:
        return f"Error al descargar: {e}", 500
