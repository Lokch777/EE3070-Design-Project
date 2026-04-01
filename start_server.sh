#!/bin/bash
# Omni Realtime Gateway — Server Startup Script
#
# Usage:
#   ./start_server.sh              # start realtime gateway (default)
#   ./start_server.sh legacy       # start original ASR/Vision/TTS backend

set -e

MODE="${1:-omni}"

echo "=================================="
echo "EE3070 Design Project — Backend"
echo "Mode: ${MODE}"
echo "=================================="
echo ""

# Locate repo root (script may be called from any directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Create / activate virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r backend/requirements.txt -q

# Ensure .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  WARNING: .env file not found!"
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "Created .env from .env.example."
    fi
    echo "Please edit .env and set DASHSCOPE_API_KEY, then re-run."
    echo ""
    read -p "Press Enter to continue anyway or Ctrl+C to exit..."
fi

# Load .env (set -a exports all sourced variables automatically)
set -a
# shellcheck source=.env
source .env
set +a

echo ""
echo "Starting server..."
echo "=================================="
echo ""

if [ "$MODE" = "legacy" ]; then
    # Original ASR/Vision/TTS backend
    HOST="${SERVER_HOST:-0.0.0.0}"
    PORT="${SERVER_PORT:-8080}"
    uvicorn backend.main:app --host "$HOST" --port "$PORT" --reload
else
    # Realtime Omni gateway (default)
    HOST="${REALTIME_HOST:-0.0.0.0}"
    PORT="${REALTIME_PORT:-8765}"
    uvicorn backend.realtime_gateway:app --host "$HOST" --port "$PORT" --reload
fi
