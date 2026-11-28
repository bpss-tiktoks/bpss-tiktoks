import os
from flask import Flask, jsonify, request, render_template_string
import yt_dlp

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

RENDER_URL = "https://bpss-tiktoks.onrender.com"

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

def build_ydl_opts(mode='video', quality='best'):
    outtmpl = os.path.join(DOWNLOAD_DIR, '%(title)s [%(id)s].%(ext)s')
    if mode == 'audio':
        return {
            'outtmpl': outtmpl,
            'format': 'bestaudio/best',
            'noplaylist': True,
        }
    if quality == '1080p':
        fmt = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
    elif quality == '720p':
        fmt = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
    else:
        fmt = 'bestvideo+bestaudio/best'
    return {
        'outtmpl': outtmpl,
        'format': fmt,
        'merge_output_format': 'mp4',
        'noplaylist': True,
    }

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NEXUS // Media Node</title>
  <style>
    :root {
      --bg: #07070c;
      --panel: #0e0e18;
      --panel-2: #141424;
      --border: rgba(168, 85, 247, 0.22);
      --border-strong: rgba(168, 85, 247, 0.55);
      --text: #f3f0ff;
      --muted: #8e88a8;
      --accent: #a855f7;
      --ok: #22c55e;
      --err: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background:
        radial-gradient(circle at 15% 10%, rgba(168, 85, 247, 0.14), transparent 45%),
        radial-gradient(circle at 85% 80%, rgba(56, 189, 248, 0.08), transparent 45%),
        var(--bg);
      color: var(--text);
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 36px 18px;
    }
    .wrap {
      width: 100%;
      max-width: 760px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 18px 22px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
    }
    .brand { display: flex; flex-direction: column; gap: 3px; }
    .brand-tag {
      font-size: 11px;
      letter-spacing: 2.4px;
      text-transform: uppercase;
      color: var(--accent);
      font-weight: 600;
    }
    .brand h1 { font-size: 20px; font-weight: 600; }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 13px;
      border-radius: 999px;
      background: var(--panel-2);
      border: 1px solid var(--border);
      font-size: 12px;
      color: var(--muted);
      cursor: pointer;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
    .dot.online { background: var(--ok); box-shadow: 0 0 10px var(--ok); }
    .dot.offline { background: var(--err); }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px 22px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .modes { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .mode-btn {
      padding: 12px 14px;
      border-radius: 10px;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--text);
      text-align: left;
      cursor: pointer;
    }
    .mode-btn.active {
      border-color: var(--border-strong);
      background: rgba(168, 85, 247, 0.14);
    }
    .mode-title { font-size: 13px; font-weight: 600; display: block; }
    .mode-sub { font-size: 11px; color: var(--muted); display: block; margin-top: 2px; }
    label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 6px; }
    input, select {
      width: 100%;
      padding: 11px 13px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      font-size: 14px;
      outline: none;
    }
    input:focus, select:focus { border-color: var(--border-strong); }
    .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    button.primary {
      flex: 1;
      min-width: 160px;
      padding: 12px 18px;
      border-radius: 10px;
      border: 1px solid var(--border-strong);
      background: linear-gradient(135deg, #7e22ce, #a855f7);
      color: #fff;
      font-weight: 600;
      font-size: 14px;
      cursor: pointer;
    }
    button.secondary {
      padding: 12px 16px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      font-size: 13px;
      cursor: pointer;
    }
    .console {
      background: #050509;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      font-family: Consolas, monospace;
      font-size: 12.5px;
      line-height: 1.55;
      color: #d8d0f7;
      min-height: 120px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 600px) { .modes, .row-2 { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div class="brand">
        <span class="brand-tag">Hybrid Node // v1.0</span>
        <h1>Media Engine</h1>
      </div>
      <div class="pill" id="healthPill" onclick="checkHealth()">
        <span class="dot" id="statusDot"></span>
        <span id="statusText">Verificando...</span>
      </div>
    </header>

    <section class="card">
      <div class="modes">
        <button type="button" class="mode-btn active" id="btnLight" onclick="setWorkload('light')">
          <span class="mode-title">Render // Liviano</span>
          <span class="mode-sub">https://bpss-tiktoks.onrender.com</span>
        </button>
        <button type="button" class="mode-btn" id="btnHeavy" onclick="setWorkload('heavy')">
          <span class="mode-title">PC Local // Pesado</span>
          <span class="mode-sub">http://127.0.0.1:5000</span>
        </button>
      </div>

      <div>
        <label for="baseUrl">Endpoint base activo</label>
        <input type="text" id="baseUrl" value="__RENDER_URL__" />
      </div>

      <div>
        <label for="mediaUrl">Enlace multimedia</label>
        <input type="url" id="mediaUrl" placeholder="https://www.tiktok.com/@usuario/video/..." />
      </div>

      <div class="row-2">
        <div>
          <label for="mode">Modo</label>
          <select id="mode">
            <option value="video" selected>Video</option>
            <option value="audio">Audio</option>
          </select>
        </div>
        <div>
          <label for="quality">Calidad</label>
          <select id="quality">
            <option value="best" selected>MÃ¡xima disponible</option>
            <option value="1080p">1080p</option>
            <option value="720p">720p</option>
          </select>
        </div>
      </div>

      <div class="actions">
        <button type="button" class="secondary" onclick="runAction('/info')">Analizar (/info)</button>
        <button type="button" class="primary" onclick="runAction('/download')">Ejecutar (/download)</button>
      </div>
    </section>

    <section class="card" style="padding: 14px 16px;">
      <div class="console" id="out">Listo. Endpoint inicial: __RENDER_URL__</div>
    </section>
  </div>

  <script>
    const RENDER_URL = "__RENDER_URL__";
    const LOCAL_URL = "http://127.0.0.1:5000";
    let workload = 'light';

    function getBase() {
      return document.getElementById('baseUrl').value.trim().replace(/\/+$/, '');
    }

    function setWorkload(mode) {
      workload = mode;
      document.getElementById('btnLight').classList.toggle('active', mode === 'light');
      document.getElementById('btnHeavy').classList.toggle('active', mode === 'heavy');
      document.getElementById('baseUrl').value = mode === 'heavy' ? LOCAL_URL : RENDER_URL;
      checkHealth();
    }

    async function checkHealth() {
      const dot = document.getElementById('statusDot');
      const txt = document.getElementById('statusText');
      const target = `${getBase()}/healthz`;
      try {
        const r = await fetch(target);
        const j = await r.json();
        if (r.ok && j.ok) {
          dot.className = 'dot online';
          txt.textContent = workload === 'heavy' ? 'PC Online' : 'Render Online';
          return;
        }
      } catch (_) {}
      dot.className = 'dot offline';
      txt.textContent = 'Sin conexiÃ³n';
    }

    async function runAction(endpoint) {
      const url = document.getElementById('mediaUrl').value.trim();
      const mode = document.getElementById('mode').value;
      const quality = document.getElementById('quality').value;
      const out = document.getElementById('out');

      if (!url) {
        out.textContent = 'Ingresa una URL vÃ¡lida primero.';
        return;
      }

      const fullEndpoint = `${getBase()}${endpoint}`;
      out.textContent = `Enviando a ${fullEndpoint}...`;

      try {
        const r = await fetch(fullEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, mode, quality })
        });
        const data = await r.json();
        out.textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        out.textContent = `Error de red: ${err.message}`;
      }
    }

    checkHealth();
  </script>
</body>
</html>
""".replace("__RENDER_URL__", RENDER_URL)

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'status': 'Servidor operativo', 'render_url': RENDER_URL})

@app.route('/info', methods=['POST', 'OPTIONS'])
def get_info():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'ok': False, 'error': 'Falta el campo url'}), 400
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = info.get('entries')
        items = []
        if entries:
            for e in entries:
                if e:
                    items.append({
                        'id': e.get('id'),
                        'title': e.get('title'),
                        'url': e.get('webpage_url') or e.get('url'),
                        'ext': e.get('ext'),
                    })
        return jsonify({
            'ok': True,
            'title': info.get('title'),
            'is_carousel_or_list': bool(items),
            'items': items,
            'formats_count': len(info.get('formats') or []),
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

@app.route('/download', methods=['POST', 'OPTIONS'])
def download_media():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    mode = (data.get('mode') or 'video').strip().lower()
    quality = (data.get('quality') or 'best').strip().lower()
    if not url:
        return jsonify({'ok': False, 'error': 'Falta el campo url'}), 400

    opts = build_ydl_opts(mode=mode, quality=quality)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
        return jsonify({
            'ok': True,
            'title': info.get('title'),
            'saved_to': filename,
        })
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
# --- ENRUTAMIENTO AUTOMATICO ENTRE SERVIDORES (LOCAL PESADO / RENDER LIVIANO) ---
import os
import urllib.request
import urllib.error

LOCAL_NODE_URL = os.environ.get("LOCAL_NODE_URL", "http://127.0.0.1:5000").rstrip("/")
RENDER_NODE_URL = os.environ.get("RENDER_NODE_URL", "https://bpss-tiktoks.onrender.com").rstrip("/")
IS_RENDER = bool(os.environ.get("RENDER"))

def _nodo_local_disponible(timeout=1.2):
    if IS_RENDER:
        return False
    try:
        with urllib.request.urlopen(f"{LOCAL_NODE_URL}/healthz", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

def elegir_servidor_automatico(media_type="video", es_pesada=True):
    """Elige automaticamente el nodo sin mostrarlo al usuario:
    - Peticiones pesadas (audio o descarga con FFmpeg/yt-dlp): prioriza PC Local si esta activa, con respaldo en Render.
    - Peticiones livianas: usa el nodo actual o Render si esta disponible.
    """
    local_ok = _nodo_local_disponible()
    if es_pesada or media_type == "audio":
        if local_ok:
            return "local", LOCAL_NODE_URL
        return "render", RENDER_NODE_URL
    if not IS_RENDER and local_ok:
        return "local", LOCAL_NODE_URL
    return "render", RENDER_NODE_URL
# --- FIN ENRUTAMIENTO AUTOMATICO ---