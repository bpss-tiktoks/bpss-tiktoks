Set-Location 'C:\tiktok-dl'
Write-Host '=== VERIFICACION FINAL BPSS TIKTOKS ===' -ForegroundColor Cyan
git status -s
Write-Host '--- Archivos activos del proyecto (sin .git ni downloads) ---' -ForegroundColor Yellow
Get-ChildItem 'C:\tiktok-dl' -Recurse -File | Where-Object { $_.FullName -notmatch '\\\.git\\' -and $_.FullName -notmatch '\\downloads\\' -and $_.FullName -notmatch '\\__pycache__\\' } | Select-Object FullName, Length | Format-Table -AutoSize
Write-Host '--- Prueba de endpoint /api/download (sin URL debe devolver 400 JSON) ---' -ForegroundColor Yellow
try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/download' -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 5 -ErrorAction Stop
} catch {
    Write-Host ("Respuesta esperada 400: " + $_.Exception.Message) -ForegroundColor Green
}
Write-Host '--- /healthz LOCAL ---' -ForegroundColor Yellow
Invoke-RestMethod -Uri 'http://127.0.0.1:5000/healthz' -TimeoutSec 5 | ConvertTo-Json -Compress