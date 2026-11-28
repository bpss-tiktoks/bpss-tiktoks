from flask import Flask, render_template, request, send_file, redirect, jsonify, Response
import yt_dlp, os, subprocess, urllib.request, time, threading, json, uuid, requests
from collections import defaultdict

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

#  CONFIG 
GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'openai/gpt-oss-120b'
MAX_TOKENS = 1000
HISTORY_LIMIT = 10
CLEANUP_AGE = 7200
MAX_FILES = 50
RATE_LIMIT = 10

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
VALID_DOMAINS = ['tiktok.com', 'instagram.com', 'facebook.com', 'fb.watch', 'youtube.com', 'youtu.be', 'x.com', 'twitter.com']

req_log = defaultdict(list)
tasks = {}

def has_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        return True
    except Exception:
        return False

FFMPEG = has_ffmpeg()

def rate_limit():
    ip = request.remote_addr
    now = time.time()
    req_log[ip] = [t for t in req_log[ip] if now - t < 60]
    if len(req_log[ip]) >= RATE_LIMIT:
        return False
    req_log[ip].append(now)
    return True

def auto_cleanup():
    now = time.time()
    try:
        files = []
        for root, dirs, fnames in os.walk(DOWNLOAD_DIR):
            for f in fnames:
                fpath = os.path.join(root, f)
                if os.path.isfile(fpath):
                    files.append((fpath, os.path.getmtime(fpath)))
        for fpath, mtime in files:
            if now - mtime > CLEANUP_AGE:
                os.remove(fpath)
        files = [(f, m) for f, m in files if os.path.exists(f)]
        files.sort(key=lambda x: x[1], reverse=True)
        for fpath, _ in files[MAX_FILES:]:
            os.remove(fpath)
    except Exception:
        pass

def resolve_short_url(url):
    if 'vm.tiktok.com' in url or 'vt.tiktok.com' in url or 'youtu.be' in url:
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', UA)
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.url
        except Exception:
            pass
    return url

def detect_platform(url):
    if 'tiktok.com' in url: return 'TikTok'
    elif 'instagram.com' in url: return 'Instagram'
    elif 'facebook.com' in url or 'fb.watch' in url: return 'Facebook'
    elif 'youtube.com' in url or 'youtu.be' in url: return 'YouTube'
    elif 'x.com' in url or 'twitter.com' in url: return 'X'
    return '?'

def is_tiktok_photo(url):
    """Detectar URL de foto/slideshow de TikTok"""
    return ('/photo/' in url or '/photo?' in url) and 'tiktok.com' in url

def is_youtube_playlist(url):
    return 'list=' in url and ('youtube.com' in url or 'youtu.be' in url)

def get_file_size(fpath):
    try:
        size = os.path.getsize(fpath)
        if size > 1024*1024: return f'{size/(1024*1024):.1f} MB'
        return f'{size/1024:.0f} KB'
    except: return ''

def find_newest_in_dir(directory):
    """Encontrar el archivo mas reciente en un directorio (recursivo)"""
    try:
        files = []
        for root, dirs, fnames in os.walk(directory):
            for f in fnames:
                fpath = os.path.join(root, f)
                if os.path.isfile(fpath):
                    files.append((fpath, os.path.getmtime(fpath)))
        if files:
            files.sort(key=lambda x: x[1], reverse=True)
            return files[0][0]
    except:
        pass
    return None

#  DESCARGA PRINCIPAL 
def do_download(task_id, url, dtype):
    platform = detect_platform(url)
    try:
        url = resolve_short_url(url)

        # TIKTOK PHOTO  gallery-dl
        if is_tiktok_photo(url):
            do_gallery_dl(task_id, url, dtype, platform)
            return

        playlist = is_youtube_playlist(url)

        if dtype == 'video':
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bv*+ba/b' if FFMPEG else 'best/b',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
                'noplaylist': not playlist,
                'http_headers': {'User-Agent': UA},
                'retries': 3,
            }
            if FFMPEG:
                opts['merge_output_format'] = 'mp4'
        else:
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
                'noplaylist': not playlist,
                'http_headers': {'User-Agent': UA},
                'retries': 3,
            }

        if playlist:
            opts['playlist_items'] = '1-10'
            opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(playlist_index)02d_%(id)s.%(ext)s')

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if playlist and info:
                fpath = find_newest_in_dir(DOWNLOAD_DIR)
                fname = os.path.relpath(fpath, DOWNLOAD_DIR) if fpath else None
                count = len([f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))])
                thumb = info.get('thumbnail') or (info.get('thumbnails')[-1].get('url') if info and info.get('thumbnails') else '')
                tasks[task_id] = {'status': 'done', 'file': fname, 'error': None, 'title': f'Playlist ({count} archivos)', 'size': '', 'platform': platform, 'thumbnail': thumb}
            else:
                fname = os.path.basename(ydl.prepare_filename(info))
                fpath = os.path.join(DOWNLOAD_DIR, fname)
                fsize = get_file_size(fpath) if os.path.exists(fpath) else ''
                title = info.get('title', '')[:80] if info else ''
                thumb = info.get('thumbnail') or (info.get('thumbnails')[-1].get('url') if info and info.get('thumbnails') else '')
                thumb = info.get('thumbnail') or (info.get('thumbnails')[-1].get('url') if info and info.get('thumbnails') else '')
                tasks[task_id] = {'status': 'done', 'file': fname, 'error': None, 'title': title, 'size': fsize, 'platform': platform, 'thumbnail': thumb, 'thumbnail': thumb}
    except Exception as e:
        err_msg = str(e)[:500]
        if '10231' in err_msg or '10204' in err_msg:
            err_msg = f'{platform}: Video geobloqueado. No disponible en esta region.'
        elif '10216' in err_msg:
            err_msg = f'{platform}: Video privado. Solo videos publicos.'
        elif 'Unsupported URL' in err_msg or 'not a valid URL' in err_msg:
            err_msg = 'URL no soportada. Verifica que sea un video publico.'
        elif 'Sign in' in err_msg or 'login' in err_msg.lower():
            err_msg = f'{platform}: Requiere login. Solo videos publicos.'
        elif 'ffmpeg' in err_msg.lower() and not FFMPEG:
            err_msg = 'ffmpeg no disponible. Build Command debe incluir: apt-get install -y ffmpeg'
        elif 'Unable to download' in err_msg:
            err_msg = f'{platform}: No se pudo descargar. Video eliminado o restringido.'
        else:
            err_msg = f'{platform}: {err_msg[:200]}'
        tasks[task_id] = {'status': 'error', 'file': None, 'error': err_msg, 'platform': platform}

#  GALLERY-DL CORREGIDO 
def do_gallery_dl(task_id, url, dtype, platform):
    try:
        outdir = os.path.join(DOWNLOAD_DIR, 'photos')
        os.makedirs(outdir, exist_ok=True)

        # Registrar archivos antes
        before = set()
        for root, dirs, fnames in os.walk(outdir):
            for f in fnames:
                before.add(os.path.join(root, f))

        # Comando CORRECTO para gallery-dl:
        # -D = directorio EXACTO (no crea subcarpetas)
        # Sin -o flags (los defaults ya descargan photos=true, videos=true)
        cmd = ['gallery-dl', '-D', outdir, '-o', 'filename=%(id)s.%(ext)s', url]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        # Buscar archivos nuevos
        after = set()
        for root, dirs, fnames in os.walk(outdir):
            for f in fnames:
                after.add(os.path.join(root, f))

        new_files = after - before

        if new_files:
            # Usar el primer archivo nuevo
            fpath = sorted(new_files)[0]
            rel = os.path.relpath(fpath, DOWNLOAD_DIR)
            thumb = info.get('thumbnail') or (info.get('thumbnails')[-1].get('url') if info and info.get('thumbnails') else '')
            tasks[task_id] = {'status': 'done', 'file': rel, 'error': None, 'title': f'{platform} Photos ({len(new_files)} archivos)', 'size': get_file_size(fpath), 'platform': platform, 'thumbnail': thumb}
        else:
            # Si no hay archivos nuevos, mostrar error de gallery-dl
            err = result.stderr.strip()[:300] if result.stderr else ''
            if not err:
                err = result.stdout.strip()[:300] if result.stdout else ''
            if result.returncode == 0 and not err:
                err = 'gallery-dl termino sin errores pero no descargo nada. Verifica que la URL sea de un post publico.'
            tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform} photos: {err}', 'platform': platform}
    except subprocess.TimeoutExpired:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform}: Timeout al descargar fotos (120s).', 'platform': platform}
    except FileNotFoundError:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': 'gallery-dl no esta instalado en el servidor.', 'platform': platform}
    except Exception as e:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform} photos: {str(e)[:200]}', 'platform': platform}

#  CHATBOT 
SYSTEM_PROMPT = """Eres el asistente de Bpss TikToks. Web que descarga en MAXIMA CALIDAD: videos (hasta 4K/8K), audio original, y fotos en resolucion original de TikTok, Instagram, Facebook, YouTube y X.

PERSONALIDAD: Amigable, directo, en espanol. Breve pero completo. Max 2 emojis.

CAPACIDADES:
1. Conversar sobre CUALQUIER tema
2. Resolver problemas tecnicos
3. Ayudar con la web:
   - Video: maxima resolucion en MP4
   - Audio: formato original (Opus/AAC) sin conversion
   - Fotos TikTok: JPG original via gallery-dl
   - Playlists YouTube: max 10 videos
   - No funciona: videos privados, DRM, Spotify
4. Escribir y explicar codigo
5. Consejos de SEO y marketing

REGLAS:
- Si preguntan por Spotify: no soportado
- Si preguntan por Live Photo: no existe
- Si hay error de descarga, dale soluciones
- No inventes features"""

def chat_with_groq(messages, last_error=None):
    if not GROQ_KEY:
        return {'reply': 'Chatbot no configurado.', 'suggestions': []}
    try:
        all_msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        if last_error:
            all_msgs.append({'role': 'system', 'content': f'El usuario acabo de recibir este error: "{last_error}". Ayudale.'})
        for m in messages[-HISTORY_LIMIT:]:
            role = m['role'] if m['role'] in ('user', 'assistant') else 'user'
            all_msgs.append({'role': role, 'content': m['content']})
        r = requests.post(GROQ_URL, headers={'Authorization': 'Bearer ' + GROQ_KEY, 'Content-Type': 'application/json'},
            json={'model': GROQ_MODEL, 'messages': all_msgs, 'max_tokens': MAX_TOKENS, 'temperature': 0.7}, timeout=45)
        data = r.json()
        reply = data['choices'][0]['message']['content']
        return {'reply': reply, 'suggestions': gen_suggestions(reply)}
    except Exception as e:
        return {'reply': f'Error: {str(e)[:200]}', 'suggestions': []}

def gen_suggestions(reply):
    r = reply.lower()
    if 'tiktok' in r or 'instagram' in r: return ['Que URL no funciona?', 'Como descargo fotos?', 'Que es geobloqueo?']
    if 'error' in r or 'falla' in r: return ['Como lo arreglo?', 'Hay otra opcion?', 'Que puede descargar?']
    if 'calidad' in r or 'resolucion' in r: return ['Que formatos soporta?', 'Cuanto pesa?', 'Por que no MP3?']
    if 'python' in r or 'codigo' in r: return ['Dame un ejemplo', 'Mas simple', 'Que es Flask?']
    return ['Que puede hacer esta web?', 'Ayudame con un error', 'Cuentame algo interesante']

#  RUTAS 
@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    if request.method == 'POST':
        if not rate_limit():
            error = 'Demasiadas peticiones. Espera 1 min.'
        else:
            url = request.form.get('url', '').strip()
            dtype = request.form.get('type', 'video')
            if not url:
                error = 'Pega una URL'
            elif not any(d in url for d in VALID_DOMAINS):
                error = 'URL no valida. Soportamos: TikTok, Instagram, Facebook, YouTube, X'
            else:
                auto_cleanup()
                task_id = str(uuid.uuid4())[:8]
                tasks[task_id] = {'status': 'processing', 'file': None, 'error': None}
                t = threading.Thread(target=do_download, args=(task_id, url, dtype))
                t.daemon = True
                t.start()
                return redirect('/status/' + task_id)
    return render_template('index.html', error=error)

@app.route('/status/<task_id>')
def status(task_id):
    return render_template('status.html', task_id=task_id)

@app.route('/api/status/<task_id>')
def api_status(task_id):
    t = tasks.get(task_id, {'status': 'error', 'file': None, 'error': 'No encontrado'})
    return jsonify(t)

@app.route('/download/<path:filename>')
def download(filename):
    # FIX: usar normpath para mantener subcarpetas (photos/xxx.jpg)
    safe = os.path.normpath(filename)
    fpath = os.path.join(DOWNLOAD_DIR, safe)
    # Seguridad: verificar que el path no escape de DOWNLOAD_DIR
    if not fpath.startswith(DOWNLOAD_DIR):
        return 'Ruta invalida', 400
    if not os.path.exists(fpath):
        return 'Archivo expirado. Descargalo de nuevo.', 404
    return send_file(fpath, as_attachment=True)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_msg = data.get('message', '')
    history = data.get('history', [])
    last_error = data.get('last_error')
    messages = history + [{'role': 'user', 'content': user_msg}]
    return jsonify(chat_with_groq(messages, last_error))

@app.route('/robots.txt')
def robots():
    return Response('User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /download/\n\nSitemap: https://bpss-tiktoks.onrender.com/sitemap.xml\n', mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap():
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://bpss-tiktoks.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url></urlset>', mimetype='application/xml')

@app.route('/health')
def health():
    disk = 0
    for root, dirs, fnames in os.walk(DOWNLOAD_DIR):
        disk += len(fnames)
    return jsonify({'status': 'ok', 'active': sum(1 for t in tasks.values() if t['status'] == 'processing'), 'files': disk, 'groq': bool(GROQ_KEY), 'ffmpeg': FFMPEG})

@app.route('/google110a1e6092696f4d.html')
def google_verify():
    return "google-site-verification: google110a1e6092696f4d.html", 200, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import json

def _descargar_bytes(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.tiktok.com/"
        }
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read()

def convertir_foto_o_animada_a_mp4(tiktok_url, salida_mp4):
    os.makedirs(os.path.dirname(os.path.abspath(salida_mp4)), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        info_cmd = ["yt-dlp", "-J", "--no-warnings", tiktok_url]
        proc = subprocess.run(info_cmd, capture_output=True, text=True, timeout=45)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "No se pudo leer el enlace de TikTok.")
        data = json.loads(proc.stdout)

        entries = data.get("entries") or [data]
        imgs = []
        audio_url = None
        mov_url = None

        for item in entries:
            if not item:
                continue
            if not audio_url and item.get("url") and item.get("vcodec") == "none":
                audio_url = item["url"]
            for f in (item.get("formats") or []):
                u = f.get("url") or ""
                vcodec = f.get("vcodec") or ""
                acodec = f.get("acodec") or ""
                ext = (f.get("ext") or "").lower()
                if not audio_url and u and vcodec == "none" and acodec != "none":
                    audio_url = u
                if not mov_url and u and vcodec != "none" and ext in ("mp4", "webm", "mov"):
                    mov_url = u
            for th in (item.get("thumbnails") or []):
                u = th.get("url") or ""
                if u and any(k in u.lower() for k in ("image", "photo", "tos-", "tiktokcdn")):
                    imgs.append((th.get("width") or 0, u))

        imgs.sort(key=lambda x: x[0], reverse=True)
        mejores_imgs = []
        vistos = set()
        for _, u in imgs:
            base = u.split("?")[0]
            if base not in vistos:
                vistos.add(base)
                mejores_imgs.append(u)

        audio_path = os.path.join(tmp, "audio.m4a")
        tiene_audio = False
        if audio_url:
            try:
                with open(audio_path, "wb") as fa:
                    fa.write(_descargar_bytes(audio_url))
                tiene_audio = os.path.getsize(audio_path) > 0
            except Exception:
                tiene_audio = False

        if mov_url:
            mov_path = os.path.join(tmp, "mov_base.mp4")
            with open(mov_path, "wb") as fm:
                fm.write(_descargar_bytes(mov_url))
            cmd = ["ffmpeg", "-y", "-i", mov_path]
            if tiene_audio:
                cmd += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
            cmd += [
                "-vf", "scale='if(gt(iw,ih),1920,-2)':'if(gt(iw,ih),-2,1920)':flags=lanczos",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", salida_mp4
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return salida_mp4

        if not mejores_imgs:
            raise RuntimeError("No se encontraron fotos ni video animado en el enlace.")

        img_path = os.path.join(tmp, "foto_0.jpg")
        with open(img_path, "wb") as fi:
            fi.write(_descargar_bytes(mejores_imgs[0]))

        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img_path]
        if tiene_audio:
            cmd += ["-i", audio_path, "-shortest"]
        else:
            cmd += ["-t", "6"]
        cmd += [
            "-vf", "scale='if(gt(iw,ih),1920,-2)':'if(gt(iw,ih),-2,1920)':flags=lanczos",
            "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p"
        ]
        if tiene_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd.append(salida_mp4)
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return salida_mp4
