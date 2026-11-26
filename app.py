from flask import Flask, render_template, request, send_file, redirect, jsonify
import yt_dlp, os, urllib.request, time, threading, json, uuid, requests
from collections import defaultdict

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
COOKIES = os.path.join(BASE, 'cookies.txt')
GROQ_KEY = os.environ.get('GROQ_API_KEY', '')
GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions'

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

req_log = defaultdict(list)
def rate_limit():
    ip = request.remote_addr
    now = time.time()
    req_log[ip] = [t for t in req_log[ip] if now - t < 60]
    if len(req_log[ip]) >= 5:
        return False
    req_log[ip].append(now)
    return True

tasks = {}

def resolve_short_url(url):
    if 'vm.tiktok.com' in url or 'vt.tiktok.com' in url:
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', UA)
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.url
        except Exception:
            pass
    return url

def do_download(task_id, url, dtype):
    try:
        url = resolve_short_url(url)
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        if dtype == 'audio':
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
                'noplaylist': True,
                'http_headers': {'User-Agent': UA},
            }
        else:
            opts = {
                'quiet': True, 'no_warnings': True,
                'format': 'best/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
                'noplaylist': True,
                'http_headers': {'User-Agent': UA},
            }
        if is_youtube:
            opts['extractor_args'] = {'youtube': {'player_client': 'mweb,tv'}}
            if os.path.exists(COOKIES):
                opts['cookiefile'] = COOKIES
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = os.path.basename(ydl.prepare_filename(info))
        tasks[task_id] = {'status': 'done', 'file': fname, 'error': None}
    except Exception as e:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': str(e)[:500]}

SYSTEM_PROMPT = "Eres el asistente de Bpss TikToks, una web para descargar videos de TikTok, Instagram y YouTube sin marca de agua. Si el usuario pega una URL, dile que la ponga en el formulario de arriba. Si tiene un problema, explicale la solucion en maximo 3 lineas en espanol. Si pregunta algo no relacionado, dile que esta web es solo para descargar videos."

def chat_with_groq(messages):
    if not GROQ_KEY:
        return 'El chatbot no esta configurado. Pega la URL en el formulario de arriba.'
    try:
        all_msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        for m in messages:
            all_msgs.append({'role': m['role'], 'content': m['content']})
        r = requests.post(GROQ_URL, headers={
            'Authorization': 'Bearer ' + GROQ_KEY,
            'Content-Type': 'application/json'
        }, json={
            'model': 'llama-3.3-70b-versatile',
            'messages': all_msgs,
            'max_tokens': 500,
            'temperature': 0.7,
        }, timeout=30)
        return r.json()['choices'][0]['message']['content']
    except Exception as e:
        return f'Error del chatbot: {str(e)[:200]}'

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
            elif not any(d in url for d in ['tiktok.com', 'instagram.com', 'youtube.com', 'youtu.be']):
                error = 'URL no valida (TikTok, Instagram, YouTube)'
            else:
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
    return json.dumps(t)

@app.route('/download/<path:filename>')
def download(filename):
    safe = os.path.basename(filename)
    fpath = os.path.join(DOWNLOAD_DIR, safe)
    if not os.path.exists(fpath):
        return 'Archivo no encontrado', 404
    return send_file(fpath, as_attachment=True)

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_msg = data.get('message', '')
    history = data.get('history', [])
    messages = history[-6:]
    messages.append({'role': 'user', 'content': user_msg})
    reply = chat_with_groq(messages)
    return jsonify({'reply': reply})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
