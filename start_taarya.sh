#!/bin/bash
echo "============================================"
echo "     TaarYa - Astronomy AI Platform"
echo "============================================"

# 1. Docker
echo "[1/4] Starting Docker Services..."
docker compose up -d
if [ $? -ne 0 ]; then
    echo "[ERROR] Docker Compose failed. Please ensure Docker is running."
    read -p "Press any key to exit..."
    exit 1
fi

# 2. Ollama
echo "[2/4] Ensuring Ollama Model (kimi-k2.5:cloud)..."
ollama pull kimi-k2.5:cloud

# 3. Python Environment
echo "[3/4] Starting Application..."
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    uv run python -m src.main
else
    # Try just uv run directly
    uv run python -m src.main
fi
