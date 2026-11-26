$cssPath = "C:\tiktok-dl\static\style.css"
$newBody = @'
body {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
  font-family: system-ui, -apple-system, sans-serif;
  background: radial-gradient(circle at top, #2a2448 0%, #141418 70%);
  color: #ffffff;
}
'@

if (-not (Test-Path $cssPath)) {
  Write-Error "No se encontro $cssPath"
  exit 1
}

$content = Get-Content -Path $cssPath -Raw
$pattern = '(?s)body\s*\{.*?\}'

if ($content -match $pattern) {
  $updated = [regex]::Replace($content, $pattern, $newBody, 1)
} else {
  $updated = $newBody + "`r`n`r`n" + $content
}

Set-Content -Path $cssPath -Value $updated -NoNewline

Set-Location "C:\tiktok-dl"
git add .
$status = git status --porcelain
if ($status) {
  git commit -m "Fondo minimalista"
  git push
} else {
  Write-Host "Sin cambios nuevos para subir."
}