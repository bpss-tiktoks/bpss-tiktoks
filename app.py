import glob
import os
import re
import threading
import time
import uuid
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

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


def _set_task(task_id, **fields):
    with tasks_lock:
        curr = tasks.get(task_id)
        if not isinstance(curr, dict):
            curr = {}
        curr.update(fields)
        tasks[task_id] = curr
        return dict(curr)


def _get_task(task_id):
    with tasks_lock:
        curr = tasks.get(task_id)
        return dict(curr) if isinstance(curr, dict) else None


def _extraer_portada(info):
    if not isinstance(info, dict):
        return None
    for key in ("thumbnail", "cover", "origin_cover", "dynamic_cover"):
        val = info.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            return val
    thumbs = info.get("thumbnails")
    if isinstance(thumbs, list):
        for item in reversed(thumbs):
            if isinstance(item, dict):
                u = item.get("url")
                if isinstance(u, str) and u.startswith(("http://", "https://")):
                    return u
    return None


def _buscar_archivo_final(task_id, modo="video"):
    candidatos = []
    for fname in os.listdir(DOWNLOAD_DIR):
        if not fname.startswith(task_id):
            continue
        if fname.endswith((".part", ".ytdl", ".temp", ".tmp")):
            continue
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
            candidatos.append((os.path.getmtime(fpath), fname))
    if not candidatos:
        return None
    candidatos.sort(reverse=True)
    if modo in ("audio", "mp3"):
        for _, fn in candidatos:
            if fn.lower().endswith((".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav")):
                return fn
    else:
        for _, fn in candidatos:
            if fn.lower().endswith((".mp4", ".webm", ".mkv", ".mov")):
                return fn
    return candidatos[0][1]


def _construir_perfiles_ytdlp(outtmpl, modo):
    base = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 25,
        "retries": 2,
        "fragment_retries": 2,
        "nocheckcertificate": True,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    if modo in ("audio", "mp3"):
        p1 = dict(base)
        p1["format"] = "bestaudio/best"
        p1["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

        p2 = dict(base)
        p2["format"] = "ba/b"

        p3 = dict(base)
        p3["format"] = "best"
        return [p1, p2, p3]

    # Modo video: intentar alta calidad con merge, luego mp4 directo, luego mejor formato disponible
    p1 = dict(base)
    p1["format"] = "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b"
    p1["merge_output_format"] = "mp4"

    p2 = dict(base)
    p2["format"] = "best[ext=mp4]/best"

    p3 = dict(base)
    p3["format"] = "best"

    return [p1, p2, p3]


def _normalizar_url(raw_url):
    u = (raw_url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def do_download(task_id, url, mode="video"):
    portada = None
    modo_limpio = (mode or "video").strip().lower()
    url_limpia = _normalizar_url(url)

    _set_task(task_id, status="processing", progress=15, mode=modo_limpio, error=None)

    try:
        if not yt_dlp:
            raise RuntimeError("yt-dlp no esta disponible en el entorno.")
        if not url_limpia or "." not in url_limpia:
            raise ValueError("Enlace no valido.")

        outtmpl = os.path.join(DOWNLOAD_DIR, f"{task_id}_%(title).70s.%(ext)s")
        perfiles = _construir_perfiles_ytdlp(outtmpl, modo_limpio)

        ultimo_error = None
        archivo_final = None

        for idx, opts in enumerate(perfiles, start=1):
            _set_task(task_id, status="processing", progress=min(85, 20 + idx * 20))
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url_limpia, download=True)
                    extra_thumb = _extraer_portada(info)
                    if extra_thumb:
                        portada = extra_thumb
                        _set_task(task_id, thumbnail=portada, cover=portada)

                    if isinstance(info, dict):
                        req_dl = info.get("requested_downloads")
                        if isinstance(req_dl, list) and req_dl:
                            fp = req_dl[0].get("filepath")
                            if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                                archivo_final = os.path.basename(fp)
                        if not archivo_final:
                            fp = info.get("_filename") or info.get("filepath")
                            if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                                archivo_final = os.path.basename(fp)

                if not archivo_final:
                    archivo_final = _buscar_archivo_final(task_id, modo_limpio)

                if archivo_final:
                    break
            except Exception as e_perfil:
                ultimo_error = e_perfil
                archivo_final = _buscar_archivo_final(task_id, modo_limpio)
                if archivo_final:
                    break

        if not archivo_final:
            archivo_final = _buscar_archivo_final(task_id, modo_limpio)

        if not archivo_final:
            raise RuntimeError(str(ultimo_error) if ultimo_error else "No se pudo completar la descarga.")

        dl_url = f"/download/{archivo_final}"
        _set_task(
            task_id,
            status="done",
            progress=100,
            file=archivo_final,
            filename=archivo_final,
            download_url=dl_url,
            url=dl_url,
            thumbnail=portada,
            cover=portada,
            error=None,
        )
    except Exception as exc:
        _set_task(
            task_id,
            status="error",
            progress=100,
            error=str(exc) or "Error al descargar.",
            thumbnail=portada,
            cover=portada,
        )


def _extraer_campos_peticion():
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


def _crear_y_lanzar_tarea(url, mode):
    task_id = uuid.uuid4().hex[:12]
    _set_task(
        task_id,
        id=task_id,
        task_id=task_id,
        status="processing",
        progress=10,
        mode=mode,
        file=None,
        filename=None,
        download_url=None,
        thumbnail=None,
        cover=None,
        error=None,
    )
    hilo = threading.Thread(target=do_download, args=(task_id, url, mode), daemon=True)
    hilo.start()
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
        "<title>Bpss TikToks</title></head><body style='font-family:sans-serif;background:#111;color:#fff;padding:24px;'>"
        "<h2>Bpss TikToks</h2>"
        "<form method='post' action='/'>"
        "<input type='text' name='url' placeholder='Pega enlace de TikTok' style='width:100%;padding:10px;margin-bottom:10px;'>"
        "<button type='submit' style='padding:10px 18px;'>Descargar</button>"
        "</form></body></html>"
    )


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url, mode = _extraer_campos_peticion()
        if url:
            task_id = _crear_y_lanzar_tarea(url, mode)
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


@app.route("/status/<task_id>", methods=["GET", "POST"])
def status_page(task_id):
    t = _get_task(task_id) or {
        "id": task_id,
        "task_id": task_id,
        "status": "processing",
        "progress": 10,
        "file": None,
        "filename": None,
        "thumbnail": None,
        "cover": None,
        "error": None,
    }
    return _render_plantilla_segura(["status.html", "index.html"], task_id=task_id, task=t)


@app.route("/api/download", methods=["GET", "POST"])
@app.route("/download", methods=["GET", "POST"])
@app.route("/start", methods=["GET", "POST"])
def start_download():
    url, mode = _extraer_campos_peticion()
    if not url:
        return jsonify({"status": "error", "error": "Falta la URL"}), 400
    task_id = _crear_y_lanzar_tarea(url, mode)
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
            "thumbnail": None,
            "cover": None,
            "error": "Tarea no encontrada o el servidor se reinicio.",
        }), 200
    if "thumbnail" not in t and t.get("cover"):
        t["thumbnail"] = t["cover"]
    if "cover" not in t and t.get("thumbnail"):
        t["cover"] = t["thumbnail"]
    return jsonify(t), 200


@app.route("/download/<path:filename>", methods=["GET"])
@app.route("/files/<path:filename>", methods=["GET"])
def serve_file(filename):
    safe_name = os.path.basename(filename)
    full_path = os.path.join(DOWNLOAD_DIR, safe_name)
    if os.path.isfile(full_path):
        return send_from_directory(DOWNLOAD_DIR, safe_name, as_attachment=True)
    # Respaldo si el nombre viene sin prefijo exacto
    matches = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{safe_name}*"))
    for m in matches:
        if os.path.isfile(m):
            return send_from_directory(DOWNLOAD_DIR, os.path.basename(m), as_attachment=True)
    return jsonify({"status": "error", "error": "Archivo no disponible."}), 404


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"ok": True}), 200


@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"status": "error", "error": "Ruta no encontrada"}), 404
    return _render_plantilla_segura(["index.html", "status.html"])


@app.errorhandler(405)
def handle_405(e):
    if request.method == "POST":
        url, mode = _extraer_campos_peticion()
        if url:
            task_id = _crear_y_lanzar_tarea(url, mode)
            return redirect(f"/status/{task_id}")
    return redirect(url_for("index"))


@app.errorhandler(500)
def handle_500(e):
    return jsonify({"status": "error", "error": "Error interno del servidor"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
