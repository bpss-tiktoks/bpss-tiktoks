from flask import Flask, render_template, request, send_file, redirect, url_for
import yt_dlp, os, urllib.request, time, threading, json
from collections import defaultdict

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

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
            req = urllib.request.Request(url, method='HEAD')
            req.add_header('User-Agent', UA)
            resp = urllib.request.urlopen(req, timeout=10)
            return resp.url
        except Exception:
            pass
    return url

def do_download(task_id, url, dtype):
    try:
        url = resolve_short_url(url)
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
                'format': 'best[ext=mp4]/best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
                'noplaylist': True,
                'http_headers': {'User-Agent': UA},
            }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            fname = os.path.basename(ydl.prepare_filename(info))
        tasks[task_id] = {'status': 'done', 'file': fname, 'error': None}
    except Exception as e:
        tasks[task_id] = {'status': 'error', 'file': None, 'error': str(e)[:300]}

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
            elif not any(d in url for d in ['tiktok.com','instagram.com','youtube.com','youtu.be']):
                error = 'URL no valida (TikTok, Instagram, YouTube)'
            else:
                import uuid
                task_id = str(uuid.uuid4())[:8]
                tasks[task_id] = {'status': 'processing', 'file': None, 'error': None}
                t = threading.Thread(target=do_download, args=(task_id, url, dtype))
                t.daemon = True
                t.start()
                return redirect(f'/status/{task_id}')
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
    return send_file(os.path.join(DOWNLOAD_DIR, safe), as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
