@echo off
REM see README.md
cd /d %~dp0backend
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
if not exist .env.local copy .env.example .env.local
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
