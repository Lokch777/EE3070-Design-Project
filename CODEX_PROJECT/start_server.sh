#!/bin/bash
# ESP32 ASR Capture Vision MVP - Server Startup Script

echo "=================================="
echo "ESP32 ASR Capture Vision MVP"
echo "=================================="
echo ""

# Check if running in backend directory
if [ ! -f "main.py" ]; then
    echo "Changing to backend directory..."
    cd backend
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Check if .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  WARNING: .env file not found!"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo ""
    echo "Please edit .env and add your API keys:"
    echo "  nano .env"
    echo ""
    read -p "Press Enter to continue or Ctrl+C to exit..."
fi

# Create images directory
mkdir -p images

# Start server
echo ""
echo "Starting server..."
echo "=================================="
echo ""

python main.py
