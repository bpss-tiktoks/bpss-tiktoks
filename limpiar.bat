@echo off
cd C:\tiktok-dl
del /f /q "'@'" 2>nul
del /f /q "DOWNLOAD_DIR" 2>nul
del /f /q "app" 2>nul
del /f /q "app.run(debug" 2>nul
del /f /q "def" 2>nul
del /f /q "elif" 2>nul
del /f /q "else" 2>nul
del /f /q "error" 2>nul
del /f /q "except" 2>nul
del /f /q "from" 2>nul
del /f /q "if" 2>nul
del /f /q "import" 2>nul
del /f /q "info" 2>nul
del /f /q "opts" 2>nul
del /f /q "os.makedirs(DOWNLOAD_DIR" 2>nul
del /f /q "powershell" 2>nul
del /f /q "return" 2>nul
del /f /q "try" 2>nul
del /f /q "url" 2>nul
del /f /q "with" 2>nul
git add -A
git commit -m "Borrar archivos basura"
git push
echo.
echo Listo. Abre GitHub y verifica.
pause
