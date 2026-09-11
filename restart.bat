@echo off
chcp 65001 >nul
taskkill /FI "WINDOWTITLE eq NeverPlayerok*" /T /F >nul 2>&1
timeout /t 2 /nobreak >nul
start "NeverPlayerok" /min cmd /c start.bat
