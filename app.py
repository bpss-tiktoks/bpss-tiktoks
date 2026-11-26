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
CLEANUP_AGE = 1800
MAX_FILES = 15
RATE_LIMIT = 5

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
VALID_DOMAINS = ['tiktok.com', 'instagram.com', 'facebook.com', 'fb.watch', 'youtube.com', 'youtu.be', 'x.com', 'twitter.com']

req_log = defaultdict(list)
tasks = {}

#  FFMPEG CHECK 
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
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
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
    return '/photo/' in url and 'tiktok.com' in url

def is_youtube_playlist(url):
    return 'list=' in url and ('youtube.com' in url or 'youtu.be' in url)

def get_file_size(fpath):
    try:
        size = os.path.getsize(fpath)
        if size > 1024*1024: return f'{size/(1024*1024):.1f} MB'
        return f'{size/1024:.0f} KB'
    except: return ''

#  DESCARGA MAXIMA CALIDAD 
def do_download(task_id, url, dtype):
    platform = detect_platform(url)
    try:
        url = resolve_short_url(url)

        # TIKTOK PHOTO  gallery-dl
        if is_tiktok_photo(url):
            do_gallery_dl(task_id, url, dtype, platform)
            return

        playlist = is_youtube_playlist(url)

        #  VIDEO: maxima calidad (bv*+ba/b = mejor video + mejor audio, sin limite de resolucion) 
        if dtype == 'video':
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bv*+ba/b',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
                'noplaylist': not playlist,
                'http_headers': {'User-Agent': UA},
                'merge_output_format': 'mp4',
                'retries': 3,
            }
            if not FFMPEG:
                opts['format'] = 'best/b'
                del opts['merge_output_format']

        #  AUDIO: original sin conversion (Opus/AAC nativo = maxima calidad) 
        elif dtype == 'audio':
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
                'noplaylist': not playlist,
                'http_headers': {'User-Agent': UA},
                'retries': 3,
            }
            # SIN FFmpegExtractAudio = mantiene Opus/AAC original (max calidad)
            # Si no hay ffmpeg, igual funciona (solo descarga el stream de audio)

        if playlist:
            opts['playlist_items'] = '1-10'
            opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(playlist_index)02d_%(id)s.%(ext)s')

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if playlist and info:
                files = sorted([f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))], key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)), reverse=True)
                fname = files[0] if files else None
                count = len(files)
                tasks[task_id] = {'status': 'done', 'file': fname, 'error': None, 'title': f'Playlist ({count} archivos)', 'size': '', 'platform': platform}
            else:
                fname = os.path.basename(ydl.prepare_filename(info))
                fpath = os.path.join(DOWNLOAD_DIR, fname)
                fsize = get_file_size(fpath) if os.path.exists(fpath) else ''
                title = info.get('title', '')[:80] if info else ''
                # Detectar extension real
                ext = os.path.splitext(fname)[1].lstrip('.')
                tasks[task_id] = {'status': 'done', 'file': fname, 'error': None, 'title': title, 'size': fsize, 'platform': platform, 'format': ext.upper()}
    except Exception as e:
        err_msg = str(e)[:500]
        if '10231' in err_msg or '10204' in err_msg:
            err_msg = f'{platform}: Video geobloqueado. No disponible en esta region.'
        elif '10216' in err_msg:
            err_msg = f'{platform}: Video privado. Solo videos publicos.'
        elif 'Unsupported URL' in err_msg or 'not a valid URL' in err_msg:
            err_msg = 'URL no soportada. Verifica que sea un video/foto publico.'
        elif 'Sign in' in err_msg or 'login' in err_msg.lower():
            err_msg = f'{platform}: Requiere login. Solo videos publicos.'
        elif 'ffmpeg' in err_msg.lower() and not FFMPEG:
            err_msg = 'ffmpeg no disponible. El Build Command debe incluir: apt-get install -y ffmpeg'
        elif 'Unable to download' in err_msg:
            err_msg = f'{platform}: No se pudo descargar. Video eliminado o restringido.'
        else:
            err_msg = f'{platform}: {err_msg[:200]}'
        tasks[task_id] = {'status': 'error', 'file': None, 'error': err_msg, 'platform': platform}

#  GALLERY-DL (fotos TikTok/IG - calidad original) 
def do_gallery_dl(task_id, url, dtype, platform):
    try:
        outdir = os.path.join(DOWNLOAD_DIR, 'photos')
        os.makedirs(outdir, exist_ok=True)
        before = set(os.listdir(outdir))

        cmd = ['gallery-dl', '-d', outdir, url]
        # gallery-dl por defecto descarga la calidad original (sin downscale)
        if dtype == 'audio':
            cmd += ['-o', 'videos=true', '-o', 'images=false']
        else:
            cmd += ['-o', 'images=true', '-o', 'videos=true']

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        after = set(os.listdir(outdir))
        new_files = after - before

        if new_files:
            fname = sorted(new_files)[0]
            fpath = os.path.join(outdir, fname)
            rel = os.path.join('photos', fname)
            tasks[task_id] = {'status': 'done', 'file': rel, 'error': None, 'title': f'{platform} Photos ({len(new_files)} archivos) - Original', 'size': get_file_size(fpath), 'platform': platform}
        elif result.returncode != 0:
            err = result.stderr[:300] if result.stderr else 'Sin archivos'
            tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform} photos: {err}', 'platform': platform}
        else:
            tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform}: No se descargo nada.', 'platform': platform}
    except subprocess.TimeoutExpired:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform}: Timeout (120s).', 'platform': platform}
    except FileNotFoundError:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': 'gallery-dl no instalado.', 'platform': platform}
    except Exception as e:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': f'{platform}: {str(e)[:200]}', 'platform': platform}

#  CHATBOT 
SYSTEM_PROMPT = """Eres el asistente de Bpss TikToks. Web que descarga en MAXIMA CALIDAD: videos (hasta 4K/8K), audio original (Opus/AAC sin conversion), y fotos en resolucion original de TikTok, Instagram, Facebook, YouTube y X.

PERSONALIDAD: Amigable, directo, en espanol. Breve pero completo. Max 2 emojis.

CAPACIDADES:
1. Conversar sobre CUALQUIER tema
2. Resolver problemas tecnicos
3. Ayudar con la web:
   - Video: maxima resolucion disponible (1080p, 4K, 8K) en MP4
   - Audio: formato original (Opus o AAC) SIN conversion a MP3 = maxima calidad
   - Fotos: resolucion original (JPG) via gallery-dl
   - Playlists YouTube: max 10 videos
   - No funciona: videos privados, DRM, Spotify
4. Escribir y explicar codigo
5. Consejos de SEO y marketing

REGLAS:
- Si preguntan por Spotify: requiere cuenta Premium + API credentials (no soportado)
- Si preguntan por Live Photo: no existe como formato descargable
- Si hay error de descarga, dale soluciones
- No inventes features
- Responde con el largo que necesite"""

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
    if 'calidad' in r or 'resolucion' in r or 'audio' in r: return ['Que formatos soporta?', 'Por que no MP3?', 'Cuanto pesa?']
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
    safe = os.path.normpath(filename)
    fpath = os.path.join(DOWNLOAD_DIR, safe)
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
    disk = len([f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))])
    return jsonify({'status': 'ok', 'active': sum(1 for t in tasks.values() if t['status'] == 'processing'), 'files': disk, 'groq': bool(GROQ_KEY), 'ffmpeg': FFMPEG})

@app.route('/google110a1e6092696f4d.html')
def google_verify():
    return "google-site-verification: google110a1e6092696f4d.html", 200, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

