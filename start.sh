#!/bin/bash
# TradeLab Paper Trading Simulator Runner

echo "=========================================================="
echo " Starting The TradeLab (Paper Trading Simulator)           "
echo " Powered by Angel One SmartAPI                            "
echo "=========================================================="

# 1. Kill any previously hanging servers on ports 8000 and 5173
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
lsof -ti:5173 | xargs kill -9 2>/dev/null || true

# 2. Start Backend
echo "Starting FastAPI Backend on port 8000..."
cd /home/pravin/Documents/Trading/papertrade/backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 3. Start Frontend
echo "Starting Vite Frontend on port 5173..."
cd /home/pravin/Documents/Trading/papertrade/frontend
npm run dev -- --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!

echo "=========================================================="
echo " Backend running at:  http://localhost:8000 (Docs: /docs) "
echo " Frontend running at: http://localhost:5173              "
echo "=========================================================="

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
