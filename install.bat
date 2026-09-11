@echo off
chcp 65001 >nul
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install wrapper-tls-requests==1.1.4
.venv\Scripts\python.exe -m pip install "tqdm>=4.67,<5"
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe installer.py
pause
