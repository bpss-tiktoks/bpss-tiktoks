from flask import Flask, render_template, request, send_file, redirect, jsonify, Response
import yt_dlp, os, urllib.request, time, threading, json, uuid, requests
from collections import defaultdict
from functools import wraps

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

#  CONFIG 
GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL = 'openai/gpt-oss-120b'  # Mejor modelo gratis (120B, 200K tokens/dia)
MAX_TOKENS = 1000  # Respuestas mas largas
HISTORY_LIMIT = 10  # Mas contexto de conversacion
MAX_DOWNLOADS_KEEP = 20  # Max archivos en disco
CLEANUP_AGE = 3600  # 1 hora
RATE_LIMIT_PER_MIN = 5

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
VALID_DOMAINS = ['tiktok.com', 'instagram.com', 'facebook.com', 'fb.watch', 'youtube.com', 'youtu.be', 'x.com', 'twitter.com']

req_log = defaultdict(list)
tasks = {}
download_errors = {}  # Ultimo error por IP (para el chatbot)

#  UTILIDADES 
def rate_limit():
    ip = request.remote_addr
    now = time.time()
    req_log[ip] = [t for t in req_log[ip] if now - t < 60]
    if len(req_log[ip]) >= RATE_LIMIT_PER_MIN:
        return False
    req_log[ip].append(now)
    return True

def auto_cleanup():
    """Borrar archivos viejos + limitar cantidad"""
    now = time.time()
    try:
        files = []
        for f in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(fpath):
                files.append((fpath, os.path.getmtime(fpath)))
        # Borrar por edad
        for fpath, mtime in files:
            if now - mtime > CLEANUP_AGE:
                os.remove(fpath)
        # Borrar por cantidad (dejar los mas recientes)
        files = [(f, m) for f, m in files if os.path.exists(f)]
        files.sort(key=lambda x: x[1], reverse=True)
        for fpath, _ in files[MAX_DOWNLOADS_KEEP:]:
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
    """Detectar plataforma para mensajes personalizados"""
    if 'tiktok.com' in url:
        return 'TikTok'
    elif 'instagram.com' in url:
        return 'Instagram'
    elif 'facebook.com' in url or 'fb.watch' in url:
        return 'Facebook'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return 'YouTube'
    elif 'x.com' in url or 'twitter.com' in url:
        return 'X (Twitter)'
    return 'desconocida'

def get_file_size(fpath):
    try:
        size = os.path.getsize(fpath)
        if size > 1024*1024:
            return f'{size/(1024*1024):.1f} MB'
        return f'{size/1024:.0f} KB'
    except:
        return ''

#  DESCARGA 
def do_download(task_id, url, dtype):
    ip = request.remote_addr
    platform = detect_platform(url)
    try:
        url = resolve_short_url(url)
        if dtype == 'audio':
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
                'noplaylist': True,
                'http_headers': {'User-Agent': UA},
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            }
        else:
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'best[height<=720]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
                'noplaylist': True,
                'http_headers': {'User-Agent': UA},
            }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = os.path.basename(ydl.prepare_filename(info))
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            fsize = get_file_size(fpath) if os.path.exists(fpath) else ''
            title = info.get('title', '')[:80] if info else ''
            tasks[task_id] = {'status': 'done', 'file': fname, 'error': None, 'title': title, 'size': fsize, 'platform': platform}
            download_errors[task_id] = None
    except Exception as e:
        err_msg = str(e)[:500]
        # Mensajes personalizados
        if '10231' in err_msg or '10204' in err_msg:
            err_msg = f'Video de {platform} no disponible en la region del servidor (geobloqueo). Prueba con otro video.'
        elif '10216' in err_msg:
            err_msg = f'Video de {platform} es privado. No se pueden descargar videos privados.'
        elif 'Unsupported URL' in err_msg or 'not a valid URL' in err_msg:
            err_msg = 'URL no soportada. Verifica que sea un video publico de TikTok, Instagram, Facebook, YouTube o X.'
        elif 'Unable to download' in err_msg:
            err_msg = f'No se pudo descargar de {platform}. El video puede estar eliminado o restringido.'
        elif 'Sign in' in err_msg or 'login' in err_msg.lower():
            err_msg = f'Este video de {platform} requiere login. Solo funcionan videos publicos.'
        else:
            err_msg = f'Error al descargar de {platform}: {err_msg[:200]}'
        tasks[task_id] = {'status': 'error', 'file': None, 'error': err_msg, 'platform': platform}
        download_errors[task_id] = err_msg

#  CHATBOT (MAXIMO) 
SYSTEM_PROMPT = """Eres el asistente de Bpss TikToks, una web que descarga videos y audios de TikTok, Instagram Reels, Facebook, YouTube Shorts y X (Twitter) sin marca de agua.

TU PERSONALIDAD:
- Amigable, directo y util
- Hablas siempre en espanol
- Eres breve pero completo (max 5 parrafos)
- Usas emojis con moderacion (1-2 por respuesta)
- Si no sabes algo, lo dices sin inventar

TUS CAPACIDADES:
1. Conversar sobre CUALQUIER tema (programacion, tecnologia, ciencia, cultura, etc.)
2. Resolver problemas tecnicos (Python, Flask, HTML, CSS, JS, redes, etc.)
3. Explicar conceptos de forma clara
4. Ayudar con la web Bpss TikToks:
   - Que plataformas soporta: TikTok, Instagram, Facebook, YouTube, X/Twitter
   - Que no funciona: videos privados, videos geobloqueados, content con DRM
   - Como usarla: pegar URL, elegir video o audio, descargar
   - Errores comunes y como solucionarlos
5. Dar consejos de SEO, marketing, desarrollo web
6. Escribir y explicar codigo

REGLAS:
- Si el usuario pregunta por un video privado o geobloqueado, explicale por que no funciona
- Si el usuario tiene un error de descarga, dale soluciones practicas
- No inventes features que la web no tiene
- Si te piden algo fuera de lo tuyo, responde igual (eres un asistente general)
- Responde con el largo que necesite (no te limites a 3 lineas)

CONTEXTO DE LA WEB:
- URL: https://bpss-tiktoks.onrender.com
- Plataforma: Flask + yt-dlp + Groq AI
- Descargas: video (MP4 hasta 720p) y audio (MP3)
- No soporta: videos privados, DRM, content de pago
- El chatbot usa Groq (modelo gpt-oss-120b)"""

def chat_with_groq(messages, last_error=None):
    if not GROQ_KEY:
        return {'reply': 'El chatbot no esta configurado. Pega la URL en el formulario de arriba.', 'suggestions': []}
    try:
        all_msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        # Inyectar contexto de error si hay uno
        if last_error:
            all_msgs.append({'role': 'system', 'content': f'CONTEXTO: El usuario acaba de recibir este error de descarga: "{last_error}". Si pregunta sobre el, explicale que paso y que puede hacer.'})
        for m in messages[-HISTORY_LIMIT:]:
            role = m['role'] if m['role'] in ('user', 'assistant') else 'user'
            all_msgs.append({'role': role, 'content': m['content']})
        r = requests.post(GROQ_URL, headers={
            'Authorization': 'Bearer ' + GROQ_KEY,
            'Content-Type': 'application/json'
        }, json={
            'model': GROQ_MODEL,
            'messages': all_msgs,
            'max_tokens': MAX_TOKENS,
            'temperature': 0.7,
        }, timeout=45)
        data = r.json()
        reply = data['choices'][0]['message']['content']
        # Generar sugerencias basadas en el tema
        suggestions = generate_suggestions(reply)
        return {'reply': reply, 'suggestions': suggestions}
    except Exception as e:
        return {'reply': f'Error del chatbot: {str(e)[:200]}. Intenta de nuevo.', 'suggestions': []}

def generate_suggestions(reply):
    """Generar preguntas sugeridas basadas en la respuesta"""
    suggestions = []
    r = reply.lower()
    if 'tiktok' in r or 'instagram' in r or 'facebook' in r:
        suggestions = ['Que URL no funciona?', 'Como descargo audio?', 'Que es geobloqueo?']
    elif 'error' in r or 'problema' in r or 'falla' in r:
        suggestions = ['Como lo arreglo?', 'Hay otra solucion?', 'Que es yt-dlp?']
    elif 'python' in r or 'codigo' in r or 'flask' in r:
        suggestions = ['Dame un ejemplo', 'Explicalo mas simple', 'Que es Flask?']
    elif 'seo' in r or 'google' in r or 'posicion' in r:
        suggestions = ['Como subo en Google?', 'Que es un backlink?', 'Dame ideas de contenido']
    else:
        suggestions = ['Cuentame algo interesante', 'Ayudame con un error', 'Que puede hacer esta web?']
    return suggestions[:3]

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
                error = 'URL no valida. Soportamos: TikTok, Instagram, Facebook, YouTube, X/Twitter'
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
    safe = os.path.basename(filename)
    fpath = os.path.join(DOWNLOAD_DIR, safe)
    if not os.path.exists(fpath):
        return 'Archivo no encontrado (puede que haya expirado). Descargalo de nuevo.', 404
    return send_file(fpath, as_attachment=True)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_msg = data.get('message', '')
    history = data.get('history', [])
    last_error = data.get('last_error')
    messages = history
    messages.append({'role': 'user', 'content': user_msg})
    result = chat_with_groq(messages, last_error)
    return jsonify(result)

@app.route('/robots.txt')
def robots():
    return Response(
        'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /download/\n\nSitemap: https://bpss-tiktoks.onrender.com/sitemap.xml\n',
        mimetype='text/plain'
    )

@app.route('/sitemap.xml')
def sitemap():
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url><loc>https://bpss-tiktoks.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>\n'
        '</urlset>',
        mimetype='application/xml'
    )

@app.route('/health')
def health():
    disk_files = len([f for f in os.listdir(DOWNLOAD_DIR) if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))])
    return jsonify({'status': 'ok', 'downloads_active': sum(1 for t in tasks.values() if t['status'] == 'processing'), 'files_on_disk': disk_files, 'groq_configured': bool(GROQ_KEY)})

@app.route('/google110a1e6092696f4d.html')
def google_verify():
    return "google-site-verification: google110a1e6092696f4d.html", 200, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
