@echo off
chcp 65001 >nul
title NeverPlayerok
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe -m app.main) else (python -m app.main)
