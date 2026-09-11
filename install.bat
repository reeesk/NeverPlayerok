@echo off
chcp 65001 >nul
python -m venv .venv
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
.venv\Scripts\python.exe -c "import requests, tls_requests; from playerokapi.account import Account; print('Playerok dependencies: OK')"
if errorlevel 1 goto :error
.venv\Scripts\python.exe installer.py
if errorlevel 1 goto :error
echo.
echo Installation completed. Run start.bat
pause
exit /b 0

:error
echo.
echo Installation failed. Check the error above.
pause
exit /b 1
