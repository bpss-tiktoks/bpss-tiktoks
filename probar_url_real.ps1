Set-Location 'C:\tiktok-dl'
$urlPrueba = 'https://vt.tiktok.com/ZSsDLNbKQ/'
Write-Host '=== PRUEBA REAL DE DESCARGA BPSS TIKTOKS ===' -ForegroundColor Cyan
Write-Host "URL: $urlPrueba" -ForegroundColor Yellow

try {
    $init = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/download' -Method Post -ContentType 'application/json' -Body (@{ url = $urlPrueba; mode = 'video' } | ConvertTo-Json) -TimeoutSec 15 -ErrorAction Stop
} catch {
    Write-Host ("Error al iniciar /api/download: " + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

$taskId = $init.task_id
if (-not $taskId) { $taskId = $init.id }
Write-Host "Task ID: $taskId" -ForegroundColor Green

$final = $null
for ($i = 1; $i -le 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $st = Invoke-RestMethod -Uri ("http://127.0.0.1:5000/api/status/" + $taskId) -TimeoutSec 10 -ErrorAction Stop
        $pct = $st.progress
        $est = $st.status
        Write-Host ("[$i] Estado: $est | Progreso: $pct%") -ForegroundColor Cyan
        if ($est -eq 'done' -or $est -eq 'error') {
            $final = $st
            break
        }
    } catch {
        Write-Host ("[$i] Reintentando consulta de estado...") -ForegroundColor Yellow
    }
}

Write-Host '=== RESULTADO FINAL ===' -ForegroundColor Magenta
if ($final) {
    $final | ConvertTo-Json -Depth 5
} else {
    Write-Host "La tarea no termino dentro del tiempo de espera." -ForegroundColor Red
}

Write-Host '=== ARCHIVOS EN C:\tiktok-dl\downloads PARA ESTA TAREA ===' -ForegroundColor Yellow
Get-ChildItem 'C:\tiktok-dl\downloads' -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "$taskId*" } | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize