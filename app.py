from flask import Flask, render_template, request, send_file
import yt_dlp, os, uuid

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def download_video(url):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_video.%(ext)s'),
        'noplaylist': True,
        'merge_output_format': 'mp4',
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_audio(url):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(id)s_audio.%(ext)s'),
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',
        }],
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
            error = 'URL no valida. Debe ser de TikTok'
        else:
            try:
                if dtype == 'audio':
                    file_path = download_audio(url)
                else:
                    file_path = download_video(url)
            except Exception as e:
                error = str(e)[:300]
    return render_template('index.html', error=error, file_path=file_path)

@app.route('/download/<path:filename>')
def download(filename):
    return send_file(os.path.join(DOWNLOAD_DIR, filename), as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
