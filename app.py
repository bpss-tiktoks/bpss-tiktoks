import os
import threading
import uuid
from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

tasks = {}
tasks_lock = threading.Lock()


def _set_task(task_id, **fields):
    with tasks_lock:
        current = tasks.get(task_id, {})
        if not isinstance(current, dict):
            current = {}
        current.update(fields)
        tasks[task_id] = current
        return dict(current)


def _get_task(task_id):
    with tasks_lock:
        current = tasks.get(task_id)
        return dict(current) if isinstance(current, dict) else None


def _extraer_portada(info):
    if not isinstance(info, dict):
        return None
    thumb = info.get("thumbnail")
    if not thumb and isinstance(info.get("thumbnails"), list):
        for item in reversed(info["thumbnails"]):
            if isinstance(item, dict) and item.get("url"):
                thumb = item["url"]
                break
    return thumb


def _buscar_archivo_descargado(out_tmpl_base, task_id):
    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(task_id) and not fname.endswith(".part") and not fname.endswith(".ytdl"):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                return fname
    return None


def do_download(task_id, url, mode="video"):
    portada = None
    archivo_final = None
    try:
        if not yt_dlp:
            raise RuntimeError("yt-dlp no esta instalado en el entorno.")
        if not url or not str(url).strip().startswith(("http://", "https://")):
            raise ValueError("URL no valida.")

        url_limpia = str(url).strip()
        modo_limpio = (mode or "video").strip().lower()
        outtmpl = os.path.join(DOWNLOAD_DIR, f"{task_id}_%(title).80s.%(ext)s")

        ydl_opts = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 25,
            "retries": 2,
        }

        if modo_limpio in ("audio", "mp3"):
            ydl_opts["format"] = "ba/b"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        else:
            ydl_opts["format"] = "bv*+ba/b"
            ydl_opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_limpia, download=True)
            portada = _extraer_portada(info)
            if portada:
                _set_task(task_id, thumbnail=portada, cover=portada)

            if isinstance(info, dict):
                req_downloads = info.get("requested_downloads")
                if isinstance(req_downloads, list) and req_downloads:
                    fp = req_downloads[0].get("filepath")
                    if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                        archivo_final = os.path.basename(fp)
                if not archivo_final:
                    fp = info.get("_filename") or info.get("filepath")
                    if fp and os.path.isfile(fp) and os.path.getsize(fp) > 0:
                        archivo_final = os.path.basename(fp)

        if not archivo_final:
            archivo_final = _buscar_archivo_descargado(outtmpl, task_id)

        if not archivo_final:
            raise RuntimeError("No se encontro el archivo final descargado.")

        _set_task(
            task_id,
            status="done",
            progress=100,
            file=archivo_final,
            filename=archivo_final,
            download_url=f"/download/{archivo_final}",
            thumbnail=portada,
            cover=portada,
            error=None,
        )
    except Exception as exc:
        _set_task(
            task_id,
            status="error",
            error=str(exc) or "Error al procesar la descarga.",
            thumbnail=portada,
            cover=portada,
        )


@app.route("/", methods=["GET", "POST"])
def index():
    for tpl in ("index.html", "status.html"):
        if os.path.exists(os.path.join(BASE_DIR, "templates", tpl)):
            return render_template(tpl)
    return jsonify({"status": "ok", "message": "Bpss TikToks activo"})


@app.route("/status/<task_id>")
def status_page(task_id):
    if os.path.exists(os.path.join(BASE_DIR, "templates", "status.html")):
        return render_template("status.html", task_id=task_id)
    if os.path.exists(os.path.join(BASE_DIR, "templates", "index.html")):
        return render_template("index.html", task_id=task_id)
    return jsonify(_get_task(task_id) or {"status": "error", "error": "Tarea no encontrada"}), 200


@app.route("/api/download", methods=["GET", "POST"])
@app.route("/download", methods=["GET", "POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url = data.get("url") or request.form.get("url") or ""
    mode = data.get("mode") or data.get("type") or request.form.get("mode") or "video"

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
        thumbnail=None,
        cover=None,
        error=None,
    )

    hilo = threading.Thread(target=do_download, args=(task_id, url, mode), daemon=True)
    hilo.start()

    return jsonify({"task_id": task_id, "id": task_id, "status": "processing"})


@app.route("/api/status/<task_id>")
def api_status(task_id):
    t = _get_task(task_id)
    if not t:
        return jsonify({"status": "error", "file": None, "error": "Tarea no encontrada"}), 404
    if "thumbnail" not in t and t.get("cover"):
        t["thumbnail"] = t["cover"]
    return jsonify(t)


@app.route("/download/<path:filename>")
def serve_file(filename):
    safe_name = os.path.basename(filename)
    return send_from_directory(DOWNLOAD_DIR, safe_name, as_attachment=True)


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
