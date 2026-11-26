$destDir = "C:\tiktok-dl"
$srcFile = Join-Path $HOME "Downloads\cookies.txt"
$dstFile = Join-Path $destDir "cookies.txt"

if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Path $destDir -Force | Out-Null
}

if (-not (Test-Path $srcFile)) {
    Write-Host "No se encontro el archivo en: $srcFile" -ForegroundColor Red
    exit 1
}

Copy-Item -Path $srcFile -Destination $dstFile -Force
Get-Item $dstFile | Select-Object Name, Length, LastWriteTime
