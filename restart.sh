#!/bin/bash
# PRA-RAG 重启脚本

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_DIR="$PROJECT_DIR/.pids"
BACKEND_PORT=4000
FRONTEND_PORT=3000
STARTUP_TIMEOUT=30

# 检查端口是否被占用
check_port() {
    lsof -ti:"$1" 2>/dev/null || true
}

# 等待端口就绪
wait_for_port() {
    local port=$1
    local name=$2
    local count=0
    while [ $count -lt $STARTUP_TIMEOUT ]; do
        if [ -n "$(check_port "$port")" ]; then
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done
    return 1
}

# 检查服务健康状态
check_health() {
    local port=$1
    curl -sf "http://localhost:$port/health" >/dev/null 2>&1
}

echo "========================================"
echo "  PRA-RAG 服务重启"
echo "========================================"

# 停止服务
bash "$PROJECT_DIR/stop.sh"

# 等待端口释放
sleep 2

# 启动服务
bash "$PROJECT_DIR/start.sh"

echo ""
echo "========================================"
echo "  启动状态检测"
echo "========================================"

FAILED=0

# 检测后端
echo -n "[检测] 后端服务 (端口 $BACKEND_PORT)... "
if wait_for_port "$BACKEND_PORT" "后端"; then
    if check_health "$BACKEND_PORT"; then
        echo "OK"
    else
        echo "FAILED (端口已监听但健康检查未通过)"
        FAILED=1
    fi
else
    echo "FAILED (端口未监听，启动超时 ${STARTUP_TIMEOUT}s)"
    FAILED=1
fi

if [ $FAILED -eq 1 ]; then
    echo ""
    echo "[错误] 后端服务启动失败，最近日志："
    echo "--- backend.log (最后 20 行) ---"
    tail -20 "$PID_DIR/backend.log" 2>/dev/null || echo "(无日志文件)"
    echo "--- END ---"
fi

# 检测前端
echo -n "[检测] 前端服务 (端口 $FRONTEND_PORT)... "
if wait_for_port "$FRONTEND_PORT" "前端"; then
    HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:$FRONTEND_PORT" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 400 ]; then
        echo "OK"
    else
        echo "FAILED (端口已监听但 HTTP 返回 $HTTP_CODE)"
        FAILED=1
    fi
else
    echo "FAILED (端口未监听，启动超时 ${STARTUP_TIMEOUT}s)"
    FAILED=1
fi

if [ $FAILED -eq 1 ]; then
    echo ""
    echo "[错误] 前端服务启动失败，最近日志："
    echo "--- frontend.log (最后 20 行) ---"
    tail -20 "$PID_DIR/frontend.log" 2>/dev/null || echo "(无日志文件)"
    echo "--- END ---"
fi

echo ""
if [ $FAILED -eq 0 ]; then
    echo "========================================"
    echo "  重启成功"
    echo "  前端: http://localhost:$FRONTEND_PORT"
    echo "  后端: http://localhost:$BACKEND_PORT"
    echo "========================================"
else
    echo "========================================"
    echo "  重启失败，请检查上方错误信息"
    echo "========================================"
    exit 1
fi
