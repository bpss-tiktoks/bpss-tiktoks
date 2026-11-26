import os
import shutil
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, send_from_directory
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)
YTDLP = shutil.which("yt-dlp") or "yt-dlp"
GALLERY_DL = shutil.which("gallery-dl") or "gallery-dl"
COOKIES_FILE = BASE_DIR / "cookies.txt"
COOKIES_ARGS = ["--cookies", str(COOKIES_FILE)] if COOKIES_FILE.exists() else []
app = Flask(__name__)
def _run(cmd, timeout=300):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout ({timeout}s)")
    except FileNotFoundError:
        raise RuntimeError(f"No se encontro: {cmd[0]}")
def _is_live(url): return "/live" in url
def _is_photo(url): return "/photo/" in url
def download_video(url, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [YTDLP, "-f", "b", "--no-playlist", *COOKIES_ARGS, "-o", str(out_dir / "%(id)s.%(ext)s"), url]
    r = _run(cmd, timeout=300)
    if r.returncode != 0: raise RuntimeError(f"yt-dlp: {r.stderr.strip()[:200]}")
    files = list(out_dir.glob("*.mp4"))
    if not files: raise RuntimeError("No se genero MP4")
    return {"type": "video", "file": files[0].name}
def download_live(url, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [YTDLP, "-f", "b", "--no-playlist", "--wait-for-video", "120", *COOKIES_ARGS, "-o", str(out_dir / "%(id)s_live.%(ext)s"), url]
    r = _run(cmd, timeout=7200)
    if r.returncode != 0: raise RuntimeError(f"Live: {r.stderr.strip()[:200]}")
    files = list(out_dir.glob("*live*.mp4"))
    if not files: raise RuntimeError("No se grabo la live")
    return {"type": "live", "file": files[0].name}
def download_photo(url, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "imgs"
    img_dir.mkdir(exist_ok=True)
    cmd_img = [GALLERY_DL, "-d", str(img_dir), "-o", 'directory=["{id}"]', "-o", "videos=false", "--no-skip", url]
    r_img = _run(cmd_img, timeout=120)
    if r_img.returncode != 0: raise RuntimeError(f"gallery-dl: {r_img.stderr.strip()[:200]}")
    imgs = [f for f in img_dir.rglob("*") if f.suffix.lower() in (".jpg",".jpeg",".png",".webp")]
    if not imgs: raise RuntimeError("No se encontraron imagenes")
    img_names = []
    for i, img in enumerate(sorted(imgs), 1):
        dest = out_dir / f"img_{i:02d}{img.suffix.lower()}"
        shutil.copy2(img, dest)
        img_names.append(dest.name)
    cmd_audio = [YTDLP, "-x", "--audio-format", "mp3", "--audio-quality", "0", "--no-playlist", *COOKIES_ARGS, "-o", str(out_dir / "%(id)s_audio.%(ext)s"), url]
    r_audio = _run(cmd_audio, timeout=60)
    audio = None
    if r_audio.returncode == 0:
        mp3s = list(out_dir.glob("*audio*.mp3"))
        if mp3s: audio = mp3s[0].name
    return {"type": "photo_post", "images": img_names, "audio": audio, "image_count": len(img_names)}
def download_tiktok(url):
    out_dir = DOWNLOADS_DIR / "latest"
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    if _is_live(url): return download_live(url, out_dir)
    elif _is_photo(url): return download_photo(url, out_dir)
    else: return download_video(url, out_dir)
@app.route("/")
def index():
    return render_template_string(open(BASE_DIR / "templates" / "index.html", encoding="utf-8").read())
@app.route("/download", methods=["POST"])
def handle_download():
    url = (request.json or {}).get("url", "").strip()
    if not url or not url.startswith("http"):
        return jsonify({"error": "URL invalida"}), 400
    try:
        result = download_tiktok(url)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/files/<path:filename>")
def serve_file(filename):
    return send_from_directory(str(DOWNLOADS_DIR / "latest"), filename)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
