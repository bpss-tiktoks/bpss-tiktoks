$batContent = @'
@echo off
cd /d "C:\tiktok-dl"
start "" powershell.exe -NoExit -Command "Set-Location 'C:\tiktok-dl'"
'@

[System.IO.File]::WriteAllText('C:\tiktok-dl\abrir_powershell.bat', $batContent, [System.Text.Encoding]::ASCII)

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut("$env:USERPROFILE\Desktop\PowerShell tiktok-dl.lnk")
$shortcut.TargetPath = "C:\tiktok-dl\abrir_powershell.bat"
$shortcut.WorkingDirectory = "C:\tiktok-dl"
$shortcut.Save()

Write-Host "Listo: C:\tiktok-dl\abrir_powershell.bat y acceso directo en el Escritorio." -ForegroundColor Green