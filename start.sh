#!/bin/bash
# PRA-RAG 启动脚本

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/Backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
PID_DIR="$PROJECT_DIR/.pids"

mkdir -p "$PID_DIR"

# 加载 .env
if [ -f "$BACKEND_DIR/.env" ]; then
    set -a
    source "$BACKEND_DIR/.env"
    set +a
fi

# 检查端口是否被占用
check_port() {
    lsof -ti:"$1" 2>/dev/null || true
}

# 等待端口就绪
wait_for_port() {
    local port=$1
    local name=$2
    local max_wait=30
    local count=0
    while [ $count -lt $max_wait ]; do
        if [ -n "$(check_port "$port")" ]; then
            echo "[OK] $name 已启动 (端口 $port)"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    echo "[WARN] $name 启动超时 (端口 $port)"
    return 1
}

echo "========================================"
echo "  PRA-RAG 服务启动"
echo "========================================"

# --- 检查后端端口 ---
if [ -n "$(check_port 4000)" ]; then
    echo "[WARN] 端口 4000 已被占用，后端可能已在运行"
    echo "       如需重启，请先执行 ./stop.sh"
else
    echo "[1/2] 启动后端服务 (FastAPI :4000)..."
    cd "$BACKEND_DIR"
    nohup python3 -m uvicorn src.server:app --host 0.0.0.0 --port 4000 > "$PID_DIR/backend.log" 2>&1 &
    echo $! > "$PID_DIR/backend.pid"
    wait_for_port 4000 "后端服务"
fi

# --- 检查前端依赖 ---
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "[INFO] 前端依赖未安装，正在安装..."
    cd "$FRONTEND_DIR"
    npm install
fi

# --- 检查前端端口 ---
if [ -n "$(check_port 3000)" ]; then
    echo "[WARN] 端口 3000 已被占用，前端可能已在运行"
    echo "       如需重启，请先执行 ./stop.sh"
else
    echo "[2/2] 启动前端服务 (Vite :3000)..."
    cd "$FRONTEND_DIR"
    nohup npx vite --port 3000 > "$PID_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
    wait_for_port 3000 "前端服务"
fi

echo ""
echo "========================================"
echo "  服务已启动"
echo "  前端: http://localhost:3000"
echo "  后端: http://localhost:4000"
echo "  日志: $PID_DIR/"
echo "========================================"
