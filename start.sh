#!/bin/bash
# VRP 最適化アプリ 起動スクリプト
# 使い方: bash start.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/venv/bin"

# 既存プロセスを停止
echo "既存プロセスを停止中..."
pkill -f "uvicorn api.main" 2>/dev/null
pkill -f "streamlit run app" 2>/dev/null
sleep 1

# FastAPI をバックグラウンドで起動
echo "FastAPI サーバーを起動中 (port 8000)..."
PYTHONPATH="$ROOT/src" "$VENV/uvicorn" api.main:app \
    --port 8000 \
    --log-level warning \
    &
FASTAPI_PID=$!

# 起動確認
sleep 3
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "FastAPI 起動完了"
else
    echo "FastAPI の起動に失敗しました"
    exit 1
fi

# Streamlit を起動（ブラウザは自動で開く）
echo "Streamlit を起動中 (port 8501)..."
echo "ブラウザで http://localhost:8501 が開きます"
echo "終了するには Ctrl+C を押してください"
echo ""
PYTHONPATH="$ROOT/src" "$VENV/streamlit" run app/streamlit_app.py \
    --server.port 8501 \
    --server.headless false

# Streamlit 終了時に FastAPI も停止
kill $FASTAPI_PID 2>/dev/null
echo "サーバーを停止しました"
