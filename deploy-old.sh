#!/bin/bash
# 智慧党建助手 - 客户服务器部署脚本（纯 docker 命令，无需 docker-compose）
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 优先找同目录下的 .env.docker，其次找 backend/.env.docker
if [ -f "$SCRIPT_DIR/.env.docker" ]; then
    ENV_FILE="$SCRIPT_DIR/.env.docker"
elif [ -f "$SCRIPT_DIR/backend/.env.docker" ]; then
    ENV_FILE="$SCRIPT_DIR/backend/.env.docker"
else
    ENV_FILE="$SCRIPT_DIR/.env.docker"  # 保持原路径让后面的检查报错提示
fi
NETWORK="party-brain-net"

# ============================================================
# 工具函数
# ============================================================
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
wait_mysql() {
    local name=$1
    local max=90
    local i=0
    log "等待 $name 就绪..."
    until docker exec "$name" mysqladmin ping -h 127.0.0.1 -uroot -proot --silent 2>/dev/null; do
        sleep 3
        i=$((i+3))
        if [ $i -ge $max ]; then
            log "❌ $name 启动超时，请检查日志: docker logs $name"
            exit 1
        fi
    done
    log "✅ $name 已就绪"
}

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
# 0. 检查环境文件
# ============================================================
if [ ! -f "$ENV_FILE" ]; then
    log "❌ 未找到环境配置文件: $ENV_FILE"
    log "   请将 .env.docker 放在与 deploy.sh 相同目录下"
    exit 1
fi

log "🚀 智慧党建助手 开始部署..."

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
# 3. 创建数据卷
# ============================================================
for vol in party-brain-mysql-data party-brain-etcd-data party-brain-minio-data party-brain-milvus-data; do
    if ! docker volume inspect "$vol" &>/dev/null; then
        docker volume create "$vol"
        log "✅ 数据卷 $vol 已创建"
    fi
done

# 创建宿主机挂载目录
mkdir -p "$SCRIPT_DIR/uploads" "$SCRIPT_DIR/exports"

# ============================================================
# 4. 启动 MySQL
# ============================================================
if docker inspect party-brain-mysql &>/dev/null; then
    log "MySQL 容器已存在，跳过创建"
    docker start party-brain-mysql 2>/dev/null || true
else
    docker run -d \
        --name party-brain-mysql \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p 3306:3306 \
        -e MYSQL_ROOT_PASSWORD=root \
        -e MYSQL_DATABASE=party_brain \
        -v party-brain-mysql-data:/var/lib/mysql \
        mysql:8.0 \
        --character-set-server=utf8mb4 \
        --collation-server=utf8mb4_unicode_ci
    log "✅ MySQL 容器已启动"
fi
wait_mysql party-brain-mysql

# ============================================================
# 5. 复用已有的 gov-milvus（服务器上已运行，跳过重新部署）
# ============================================================
if docker inspect gov-milvus &>/dev/null; then
    log "✅ 检测到 gov-milvus，复用已有 Milvus 实例"
    # 获取 gov-milvus 所在的网络，把当前网络也连上去
    GOV_NET=$(docker inspect gov-milvus --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')
    if [ -n "$GOV_NET" ] && [ "$GOV_NET" != "$NETWORK" ]; then
        docker network connect "$GOV_NET" party-brain-mysql 2>/dev/null || true
        log "✅ 后续将把 backend 加入网络: $GOV_NET"
    fi
    MILVUS_HOST_OVERRIDE="gov-milvus"
else
    log "⚠️  未找到 gov-milvus，跳过 Milvus（知识库功能不可用）"
    MILVUS_HOST_OVERRIDE=""
fi

# ============================================================
# 7. 启动后端
# ============================================================
if docker inspect party-brain-backend &>/dev/null; then
    docker start party-brain-backend 2>/dev/null || true
else
    EXTRA_ENV=""
    [ -n "$MILVUS_HOST_OVERRIDE" ] && EXTRA_ENV="-e MILVUS_HOST=$MILVUS_HOST_OVERRIDE"
    docker run -d \
        --name party-brain-backend \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p 8000:8000 \
        --env-file "$ENV_FILE" \
        $EXTRA_ENV \
        --add-host=host.docker.internal:host-gateway \
        -v "$SCRIPT_DIR/uploads:/app/uploads" \
        -v "$SCRIPT_DIR/exports:/app/exports" \
        party-brain-backend:latest
    log "✅ 后端容器已启动"
fi
wait_running party-brain-backend
# 把后端加入 gov-milvus 所在的网络（容器间通信）
if [ -n "$MILVUS_HOST_OVERRIDE" ]; then
    GOV_NET=$(docker inspect gov-milvus --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' 2>/dev/null | awk '{print $1}')
    if [ -n "$GOV_NET" ] && [ "$GOV_NET" != "$NETWORK" ]; then
        docker network connect "$GOV_NET" party-brain-backend 2>/dev/null && log "✅ backend 已加入网络 $GOV_NET" || true
    fi
fi
sleep 3

# ============================================================
# 8. 启动前端
# ============================================================
if docker inspect party-brain-frontend &>/dev/null; then
    docker start party-brain-frontend 2>/dev/null || true
else
    docker run -d \
        --name party-brain-frontend \
        --network "$NETWORK" \
        --restart unless-stopped \
        -p 80:80 \
        party-brain-frontend:latest
    log "✅ 前端容器已启动"
fi
wait_running party-brain-frontend

# ============================================================
# 完成
# ============================================================
echo ""
echo "✅ 部署完成！"
echo "================================"
echo "  前端界面: http://$(hostname -I | awk '{print $1}')"
echo "  API文档:  http://$(hostname -I | awk '{print $1}'):8000/docs"
echo "  默认账号: admin / admin123"
echo "================================"
echo ""
echo "常用命令："
echo "  查看日志: docker logs -f party-brain-backend"
echo "  停止全部: bash $(basename "$0" .sh)-stop.sh"
echo "  容器状态: docker ps --filter name=party-brain"
