#!/bin/bash
# Start Semantic Agent locally

cd "$(dirname "$0")"

echo "🚀 Starting JIRA Semantic Agent..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# Install dependencies if needed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

echo "Starting server on http://localhost:8000"
echo "Press Ctrl+C to stop"
echo ""

python -m uvicorn semantic_app:app --host 0.0.0.0 --port 8000 --reload
