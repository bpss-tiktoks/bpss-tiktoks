Set-Location 'C:\tiktok-dl'
Write-Host '=== LIMPIEZA FINAL DE SCRIPTS TEMPORALES Y CACHES ===' -ForegroundColor Cyan
@('paso1_limpiar_ver.ps1','revisar_estado_actual.ps1','reconstruir_app.ps1','local_flask.log','local_flask_err.log') | ForEach-Object {
    $fp = Join-Path 'C:\tiktok-dl' $_
    if (Test-Path $fp) { Remove-Item $fp -Force -ErrorAction SilentlyContinue; Write-Host "Eliminado: $_" -ForegroundColor Green }
}
Get-ChildItem 'C:\tiktok-dl' -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem 'C:\tiktok-dl' -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host '=== SINCRONIZACION LIMPIA CON GITHUB ===' -ForegroundColor Cyan
git add -A
$st = git status -s
if ($st) {
    $st
    git commit -m "feat: fotos a MP4 HD, animadas HD, caratula en app y limpieza del repo"
    git push origin HEAD
} else {
    Write-Host 'No hay cambios pendientes en Git.' -ForegroundColor Yellow
}

Write-Host '=== VERIFICANDO SERVIDOR LOCAL EN PUERTO 5000 ===' -ForegroundColor Cyan
$escucha = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if (-not $escucha) {
    $runner = "import wsgi`nwsgi.app.run(host='127.0.0.1', port=5000, threaded=True)"
    [System.IO.File]::WriteAllText('C:\tiktok-dl\run_local.py', $runner, [System.Text.Encoding]::UTF8)
    Start-Process -FilePath 'python' -ArgumentList '-u','run_local.py' -WorkingDirectory 'C:\tiktok-dl' -RedirectStandardOutput 'C:\tiktok-dl\local_flask.log' -RedirectStandardError 'C:\tiktok-dl\local_flask_err.log' -WindowStyle Hidden
    Start-Sleep -Seconds 2
}
for ($i=1; $i -le 8; $i++) {
    try {
        $h = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/healthz' -TimeoutSec 4 -ErrorAction Stop
        Write-Host ('LOCAL /healthz -> ' + ($h | ConvertTo-Json -Compress)) -ForegroundColor Green
        break
    } catch { Start-Sleep -Seconds 1 }
}