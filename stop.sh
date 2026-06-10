#!/bin/bash
# PRA-RAG 停止脚本

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$PROJECT_DIR/.pids"

echo "========================================"
echo "  PRA-RAG 服务停止"
echo "========================================"

# 停止后端
if [ -f "$PID_DIR/backend.pid" ]; then
    PID=$(cat "$PID_DIR/backend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "[OK] 后端服务已停止 (PID: $PID)"
    else
        echo "[INFO] 后端进程已不存在 (PID: $PID)"
    fi
    rm -f "$PID_DIR/backend.pid"
else
    # 尝试按端口查找
    PIDS=$(lsof -ti:4000 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill
        echo "[OK] 后端服务已停止 (PID: $(echo $PIDS | tr '\n' ' '), 端口 4000)"
    else
        echo "[INFO] 后端服务未运行"
    fi
fi

# 停止前端
if [ -f "$PID_DIR/frontend.pid" ]; then
    PID=$(cat "$PID_DIR/frontend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        # vite 可能产生子进程，杀掉整个进程组
        kill -- -"$PID" 2>/dev/null || kill "$PID"
        echo "[OK] 前端服务已停止 (PID: $PID)"
    else
        echo "[INFO] 前端进程已不存在 (PID: $PID)"
    fi
    rm -f "$PID_DIR/frontend.pid"
else
    PIDS=$(lsof -ti:3000 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill
        echo "[OK] 前端服务已停止 (PID: $(echo $PIDS | tr '\n' ' '), 端口 3000)"
    else
        echo "[INFO] 前端服务未运行"
    fi
fi

echo "========================================"
echo "  所有服务已停止"
echo "========================================"
