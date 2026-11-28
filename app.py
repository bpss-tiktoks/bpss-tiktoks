import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory

try:
    import yt_dlp
except Exception:
    yt_dlp = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)

tasks = {}
tasks_lock = threading.Lock()
HAS_FFMPEG = shutil.which("ffmpeg") is not None
VIDEO_EXTS = (".mp4", ".webm", ".mkv", ".mov")
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav")
MAX_FILE_AGE_SECONDS = 1200


def _estado_path(task_id):
    return os.path.join(DOWNLOAD_DIR, f"{task_id}.state.json")


def _guardar_estado_disco(task_id, data):
    try:
        with open(_estado_path(task_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _cargar_estado_disco(task_id):
    p = _estado_path(task_id)
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception:
            pass
    return None


def _set_task(task_id, **fields):
    fields.pop("task_id", None)
    fields.pop("thumbnail", None)
    fields.pop("cover", None)
    fields["updated_at"] = time.time()
    with tasks_lock:
        curr = tasks.get(task_id)
        if not isinstance(curr, dict):
            curr = _cargar_estado_disco(task_id) or {}
        curr.pop("thumbnail", None)
        curr.pop("cover", None)
        curr.update(fields)
        if "download_url" in curr and curr["download_url"] and not curr.get("url"):
            curr["url"] = curr["download_url"]
        tasks[task_id] = curr
        snap = dict(curr)
    _guardar_estado_disco(task_id, snap)
    return snap


def _get_task(task_id):
    with tasks_lock:
        curr = tasks.get(task_id)
        snap = dict(curr) if isinstance(curr, dict) else None
    if snap is None:
        disk = _cargar_estado_disco(task_id)
        if isinstance(disk, dict):
            with tasks_lock:
                tasks[task_id] = dict(disk)
            snap = dict(disk)
    if isinstance(snap, dict):
        snap.pop("thumbnail", None)
        snap.pop("cover", None)
        if snap.get("status") == "processing":
            updated = snap.get("updated_at") or 0
            if time.time() - updated > 120:
                snap["status"] = "error"
                snap["progress"] = 100
                snap["error"] = "Tiempo de espera agotado en el servidor."
                _set_task(task_id, **snap)
    return snap


def _limpiar_archivos_antiguos():
    ahora = time.time()
    try:
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                if ahora - os.path.getmtime(fpath) > MAX_FILE_AGE_SECONDS:
                    os.remove(fpath)
            except Exception:
                pass
    except Exception:
        pass


def _buscar_archivo_final(task_id, modo="video"):
    candidatos = []
    try:
        entries = os.listdir(DOWNLOAD_DIR)
    except Exception:
        return None
    for fname in entries:
        if not fname.startswith(task_id):
            continue
        if fname.endswith((".part", ".ytdl", ".temp", ".tmp", ".json", ".jpg", ".jpeg", ".png", ".webp")):
            continue
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
            candidatos.append((os.path.getmtime(fpath), fname))
    if not candidatos:
        return None
    candidatos.sort(reverse=True)
    if modo in ("audio", "mp3"):
        for _, fn in candidatos:
            if fn.lower().endswith(AUDIO_EXTS):
                return fn
    else:
        for _, fn in candidatos:
            if fn.lower().endswith(VIDEO_EXTS):
                return fn
    return candidatos[0][1]


def _normalizar_url(raw_url):
    u = (raw_url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _construir_perfiles(outtmpl, modo):
    base = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "writethumbnail": False,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 18,
        "retries": 1,
        "fragment_retries": 1,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    if modo in ("audio", "mp3"):
        perfiles = []
        if HAS_FFMPEG:
            p_mp3 = dict(base)
            p_mp3["format"] = "bestaudio/best"
            p_mp3["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }]
            perfiles.append(p_mp3)
        p_ba = dict(base)
        p_ba["format"] = "ba/b"
        perfiles.append(p_ba)
        return perfiles

    p_hd = dict(base)
    p_hd["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
    if HAS_FFMPEG:
        p_hd["merge_output_format"] = "mp4"

    p_direct = dict(base)
    p_direct["format"] = "best[ext=mp4]/best"

    return [p_hd, p_direct]


def _intentar_cli_fallback(url_limpia, outtmpl, modo):
    try:
        cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-write-thumbnail", "--socket-timeout", "18", "-o", outtmpl]
        if modo in ("audio", "mp3"):
            if HAS_FFMPEG:
                cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "128", "-f", "bestaudio/best"]
            else:
                cmd += ["-f", "ba/b"]
        else:
            cmd += ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"]
        cmd.append(url_limpia)
        subprocess.run(cmd, timeout=60, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def do_download(task_id, url, mode="video"):
    _limpiar_archivos_antiguos()
    titulo = None
    modo_limpio = (mode or "video").strip().lower()
    if modo_limpio not in ("video", "audio", "mp3"):
        modo_limpio = "video"
    url_limpia = _normalizar_url(url)
    _set_task(task_id, status="processing", progress=20, mode=modo_limpio, error=None)

    try:
        if not url_limpia or "." not in url_limpia:
            raise ValueError("Enlace no valido.")

        outtmpl = os.path.join(DOWNLOAD_DIR, f"{task_id}_%(title).60s.%(ext)s")
        archivo_final = None
        ultimo_error = None

        if yt_dlp is not None:
            perfiles = _construir_perfiles(outtmpl, modo_limpio)
            for idx, opts in enumerate(perfiles, start=1):
                _set_task(task_id, status="processing", progress=min(75, 20 + idx * 25))
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url_limpia, download=True)
                        if isinstance(info, dict) and info.get("title"):
                            titulo = str(info.get("title"))
                            _set_task(task_id, title=titulo)
                        archivo_final = _buscar_archivo_final(task_id, modo_limpio)
                        if archivo_final:
                            break
                except Exception as exc_p:
                    ultimo_error = exc_p
                    archivo_final = _buscar_archivo_final(task_id, modo_limpio)
                    if archivo_final:
                        break

        if not archivo_final:
            _set_task(task_id, status="processing", progress=88)
            _intentar_cli_fallback(url_limpia, outtmpl, modo_limpio)
            archivo_final = _buscar_archivo_final(task_id, modo_limpio)

        if not archivo_final:
            raise RuntimeError(str(ultimo_error) if ultimo_error else "No se pudo descargar el video.")

        dl_url = f"/files/{archivo_final}"
        _set_task(
            task_id,
            status="done",
            progress=100,
            title=titulo,
            file=archivo_final,
            filename=archivo_final,
            download_url=dl_url,
            url=dl_url,
            error=None,
        )
    except Exception as exc:
        _set_task(
            task_id,
            status="error",
            progress=100,
            title=titulo,
            error=str(exc) or "Error en la descarga.",
        )


def _extraer_campos():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    url = (
        data.get("url")
        or data.get("link")
        or request.form.get("url")
        or request.form.get("link")
        or request.args.get("url")
        or ""
    ).strip()
    mode = (
        data.get("mode")
        or data.get("type")
        or data.get("format")
        or request.form.get("mode")
        or request.form.get("type")
        or request.form.get("format")
        or request.args.get("mode")
        or "video"
    ).strip().lower()
    return url, mode


def _lanzar_tarea(url, mode):
    task_id = uuid.uuid4().hex[:12]
    _set_task(
        task_id,
        id=task_id,
        status="processing",
        progress=10,
        mode=mode,
        title=None,
        file=None,
        filename=None,
        download_url=None,
        error=None,
    )
    threading.Thread(target=do_download, args=(task_id, url, mode), daemon=True).start()
    return task_id


def _render_plantilla_segura(nombres, **ctx):
    for name in nombres:
        full = os.path.join(TEMPLATE_DIR, name)
        if os.path.isfile(full):
            try:
                return render_template(name, **ctx)
            except Exception:
                pass
    return (
        "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Bpss TikToks</title></head><body style='font-family:sans-serif;background:#0e0b16;color:#fff;padding:24px;'>"
        "<h2>Bpss TikToks</h2>"
        "<form method='post' action='/'>"
        "<input type='text' name='url' placeholder='Pega el enlace aqui' style='width:100%;padding:10px;margin-bottom:10px;'>"
        "<button type='submit' name='type' value='video' style='padding:10px 18px;'>Video HD</button>"
        "<button type='submit' name='type' value='audio' style='padding:10px 18px;'>Audio</button>"
        "</form></body></html>"
    )


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url, mode = _extraer_campos()
        if url:
            task_id = _lanzar_tarea(url, mode)
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "task_id": task_id,
                    "id": task_id,
                    "status": "processing",
                    "redirect": f"/status/{task_id}",
                    "status_url": f"/status/{task_id}",
                })
            return redirect(f"/status/{task_id}")
    return _render_plantilla_segura(["index.html", "status.html"])


@app.route("/sobre", methods=["GET"])
def sobre():
    return _render_plantilla_segura(["about.html", "index.html"])


@app.route("/sitemap.xml", methods=["GET"])
def sitemap():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://bpss-tiktoks.onrender.com/</loc></url>'
        '<url><loc>https://bpss-tiktoks.onrender.com/sobre</loc></url>'
        '</urlset>'
    )
    return Response(xml, mimetype="application/xml")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    msg = str(payload.get("message") or "").strip().lower()
    if "audio" in msg or "mp3" in msg:
        reply = "Pega el enlace y pulsa Audio para extraer el sonido."
    elif "privado" in msg or "error" in msg:
        reply = "Solo funcionan enlaces publicos. Verifica que el enlace sea completo y publico."
    else:
        reply = "Pega la URL del video publico arriba y elige Video HD o Audio."
    return jsonify({
        "reply": reply,
        "suggestions": ["Descargar video HD", "Extraer audio", "Enlaces publicos"]
    })


@app.route("/status/<task_id>", methods=["GET", "POST"])
def status_page(task_id):
    t = _get_task(task_id) or {
        "id": task_id,
        "task_id": task_id,
        "status": "processing",
        "progress": 10,
        "file": None,
        "filename": None,
        "error": None,
    }
    return _render_plantilla_segura(["status.html", "index.html"], task_id=task_id, task=t)


@app.route("/api/download", methods=["GET", "POST"])
@app.route("/start", methods=["GET", "POST"])
def start_download():
    url, mode = _extraer_campos()
    if not url:
        return jsonify({"status": "error", "error": "Falta la URL"}), 400
    task_id = _lanzar_tarea(url, mode)
    return jsonify({
        "task_id": task_id,
        "id": task_id,
        "status": "processing",
        "redirect": f"/status/{task_id}",
        "status_url": f"/status/{task_id}",
    })


@app.route("/api/status/<task_id>", methods=["GET", "POST"])
@app.route("/status_data/<task_id>", methods=["GET"])
def api_status(task_id):
    t = _get_task(task_id)
    if not t:
        return jsonify({
            "id": task_id,
            "task_id": task_id,
            "status": "error",
            "progress": 100,
            "file": None,
            "filename": None,
            "error": "Tarea no encontrada.",
        }), 200
    return jsonify(t), 200


@app.route("/files/<path:filename>", methods=["GET"])
@app.route("/archivo/<path:filename>", methods=["GET"])
@app.route("/download/<path:filename>", methods=["GET"])
def serve_file(filename):
    safe_name = os.path.basename(filename)
    full_path = os.path.join(DOWNLOAD_DIR, safe_name)
    if os.path.isfile(full_path):
        return send_from_directory(DOWNLOAD_DIR, safe_name, as_attachment=True)
    matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{safe_name}*"))
    for m in matches:
        if os.path.isfile(m):
            return send_from_directory(DOWNLOAD_DIR, os.path.basename(m), as_attachment=True)
    return jsonify({"status": "error", "error": "Archivo no disponible."}), 404


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True, "ffmpeg": HAS_FFMPEG, "yt_dlp": yt_dlp is not None}), 200


@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": "Ruta no encontrada"}), 404
    return _render_plantilla_segura(["404.html", "index.html"])


@app.errorhandler(405)
def handle_405(e):
    if request.method == "POST":
        url, mode = _extraer_campos()
        if url:
            task_id = _lanzar_tarea(url, mode)
            return redirect(f"/status/{task_id}")
    return redirect("/")


@app.errorhandler(500)
def handle_500(e):
    detalle = str(getattr(e, "original_exception", e) or "Error interno del servidor")
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"status": "error", "error": detalle}), 500
    try:
        return _render_plantilla_segura(["index.html", "status.html"], error=detalle)
    except Exception:
        return jsonify({"status": "error", "error": detalle}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
