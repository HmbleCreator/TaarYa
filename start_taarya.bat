@echo off
echo ============================================
echo      TaarYa - Astronomy AI Platform
echo ============================================

:: 1. Docker
echo [1/4] Starting Docker Services...
docker-compose up -d
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Compose failed. Please ensure Docker Desktop is running.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

:: 2. Ollama
echo [2/4] Ensuring Ollama Model (kimi-k2.5:cloud)...
ollama pull kimi-k2.5:cloud
IF %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Ollama pull failed. Ensure Ollama is installed and running.
)

:: 3. Python Environment
echo [3/4] Starting Application...
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    uv run python -m src.main
) else (
    echo [ERROR] Virtual environment not found (.venv). Please run 'uv sync' or create venv.
    pause >nul
    exit /b 1
)

pause
