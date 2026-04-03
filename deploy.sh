#!/bin/bash
# ============================================================
# 智慧党建助手 — 一键部署脚本（纯 docker 命令，无需 docker-compose）
#
# 使用方式：
#   首次部署：  bash deploy.sh
#   重新构建：  bash deploy.sh --rebuild
#   查看状态：  bash deploy.sh --status
#   停止服务：  bash deploy.sh --stop
#   查看日志：  bash deploy.sh --logs [frontend|backend]
#
# 部署后数据库会自动初始化（党员、模板、政策切片等）
# 默认账号：admin / admin123
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/backend/.env.docker"
NETWORK="party-brain-net"

# ============================================================
# 工具函数
# ============================================================
log()  { echo "[$(date '+%H:%M:%S')] $*"; }

wait_running() {
    local name=$1
    local max=30
    local i=0
    log "等待 $name 运行..."
    until docker inspect --format='{{.State.Running}}' "$name" 2>/dev/null | grep -q "true"; do
        sleep 2
        i=$((i+2))
        if [ $i -ge $max ]; then
            log "❌ $name 未能启动，请检查日志: docker logs $name"
            exit 1
        fi
    done
    log "✅ $name 运行中"
}

# ============================================================
# 命令分发
# ============================================================
case "${1:-}" in
    --stop)
        log "正在停止所有服务..."
        for name in party-brain-frontend party-brain-backend; do
            if docker inspect "$name" &>/dev/null; then
                docker stop "$name" && docker rm "$name" 2>/dev/null
                log "✅ $name 已停止并移除"
            fi
        done
        log "✅ 所有服务已停止"
        exit 0
        ;;
    --status)
        docker ps --filter name=party-brain --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        exit 0
        ;;
    --logs)
        docker logs -f --tail=100 party-brain-${2:-backend}
        exit 0
        ;;
    --rebuild)
        log "🔨 重新构建并部署..."
        # 停止并移除旧容器
        for name in party-brain-frontend party-brain-backend; do
            docker stop "$name" 2>/dev/null && docker rm "$name" 2>/dev/null || true
        done
        # 重新构建镜像
        log "构建后端镜像..."
        docker build -t party-brain-backend:latest "$SCRIPT_DIR/backend"
        log "构建前端镜像..."
        docker build -t party-brain-frontend:latest "$SCRIPT_DIR/frontend"
        # 继续往下走启动流程
        ;;
    ""|--start)
        log "🚀 智慧党建助手 一键部署启动..."
        ;;
    *)
        echo "用法: bash deploy.sh [选项]"
        echo ""
        echo "选项："
        echo "  (无参数)    首次部署/启动服务"
        echo "  --rebuild   重新构建镜像并部署"
        echo "  --stop      停止所有服务"
        echo "  --status    查看服务状态"
        echo "  --logs      查看日志（默认backend，可指定: --logs frontend）"
        exit 0
        ;;
esac

# ============================================================
# 0. 检查环境文件
# ============================================================
if [ ! -f "$ENV_FILE" ]; then
    log "❌ 未找到环境配置文件: $ENV_FILE"
    log "   请确认 backend/.env.docker 文件存在"
    exit 1
fi

# ============================================================
# 1. 加载镜像（如果使用离线包）
# ============================================================
IMAGE_PACK="$SCRIPT_DIR/docker-images/party-brain-images.tar.gz"
if [ -f "$IMAGE_PACK" ]; then
    log "📦 检测到镜像包，正在加载..."
    docker load < "$IMAGE_PACK"
    log "✅ 镜像加载完成"
fi

# ============================================================
# 2. 创建网络
# ============================================================
if ! docker network inspect "$NETWORK" &>/dev/null; then
    docker network create "$NETWORK"
    log "✅ 网络 $NETWORK 已创建"
else
    log "✅ 网络 $NETWORK 已存在"
fi

# ============================================================
# 3. 创建数据卷和宿主机目录
# ============================================================
if ! docker volume inspect "party-brain-data" &>/dev/null; then
    docker volume create "party-brain-data"
    log "✅ 数据卷 party-brain-data 已创建"
fi
mkdir -p "$SCRIPT_DIR/uploads" "$SCRIPT_DIR/exports"

# ============================================================
# 4. 构建镜像（如果还没构建过）
# ============================================================
if ! docker image inspect party-brain-backend:latest &>/dev/null; then
    log "构建后端镜像..."
    docker build -t party-brain-backend:latest "$SCRIPT_DIR/backend"
fi
if ! docker image inspect party-brain-frontend:latest &>/dev/null; then
    log "构建前端镜像..."
    docker build -t party-brain-frontend:latest "$SCRIPT_DIR/frontend"
fi

# ============================================================
# 5. 启动后端
# ============================================================
if docker container inspect party-brain-backend &>/dev/null; then
    docker start party-brain-backend 2>/dev/null || true
else
    docker run -d \
        --name party-brain-backend \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p 8000:8000 \
        --env-file "$ENV_FILE" \
        --add-host=host.docker.internal:host-gateway \
        -v party-brain-data:/app/data \
        -v "$SCRIPT_DIR/uploads:/app/uploads" \
        -v "$SCRIPT_DIR/exports:/app/exports" \
        party-brain-backend:latest
    log "✅ 后端容器已启动"
fi
wait_running party-brain-backend
sleep 3

# ============================================================
# 6. 启动前端
# ============================================================
if docker container inspect party-brain-frontend &>/dev/null; then
    docker start party-brain-frontend 2>/dev/null || true
else
    docker run -d \
        --name party-brain-frontend \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p 8001:80 \
        party-brain-frontend:latest
    log "✅ 前端容器已启动"
fi
wait_running party-brain-frontend

# ============================================================
# 等待后端就绪
# ============================================================
log "等待后端 API 就绪..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://localhost:8000/health | grep -q "ok" 2>/dev/null; then
        break
    fi
    sleep 3
    WAITED=$((WAITED+3))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    log "⚠️  后端启动超时，请检查日志: docker logs party-brain-backend"
else
    log "✅ 后端 API 已就绪"
fi

# ============================================================
# 完成
# ============================================================
echo ""
echo "✅ 部署完成！"
echo "============================================"
echo "  🌐 前端界面:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8001"
echo "  📖 API文档:   http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8000/docs"
echo "  👤 默认账号:  admin / admin123"
echo "============================================"
echo ""
echo "  常用命令："
echo "    查看状态:  bash deploy.sh --status"
echo "    查看日志:  bash deploy.sh --logs"
echo "    停止服务:  bash deploy.sh --stop"
echo "    重新部署:  bash deploy.sh --rebuild"
echo "============================================"
