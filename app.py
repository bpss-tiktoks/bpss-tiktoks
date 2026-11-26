from flask import Flask, render_template, request, send_file
import yt_dlp, os, urllib.request

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

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

def download_video(url):
    url = resolve_short_url(url)
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best[ext=mp4]/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
        'noplaylist': True,
        'http_headers': {'User-Agent': UA},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_audio(url):
    url = resolve_short_url(url)
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
        'noplaylist': True,
        'http_headers': {'User-Agent': UA},
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '0'}],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    file_path = None
    if request.method == 'POST':
        url = request.form.get('url', '').strip()
        dtype = request.form.get('type', 'video')
        if not url:
            error = 'Pega una URL de TikTok'
        elif 'tiktok.com' not in url:
            error = 'URL no valida'
        else:
            try:
                file_path = download_audio(url) if dtype == 'audio' else download_video(url)
            except Exception as e:
                error = str(e)[:300]
    return render_template('index.html', error=error, file_path=file_path)

@app.route('/download/<path:filename>')
def download(filename):
    return send_file(os.path.join(DOWNLOAD_DIR, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
