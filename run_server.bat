@echo off
cd /d "%~dp0"
title Governed Inventory AI Agent
echo.
echo  Open in browser: http://localhost:8001  (or http://127.0.0.1:8001)
echo  API docs:        http://localhost:8001/docs
echo  Close this window to stop the server.
echo.
python -m uvicorn main:app --reload --host localhost --port 8001
if errorlevel 1 (
  echo.
  echo If port 8001 failed, edit this file and try port 8000 or 8080.
  pause
)
