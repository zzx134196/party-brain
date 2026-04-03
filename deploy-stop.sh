#!/bin/bash
# 智慧党建助手 - 停止所有容器

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "正在停止所有服务..."

for name in party-brain-frontend party-brain-backend; do
    if docker inspect "$name" &>/dev/null; then
        docker stop "$name" && log "✅ $name 已停止"
    fi
done

echo ""
echo "✅ 所有服务已停止"
echo "如需彻底清除容器（保留数据卷）："
echo "  docker rm party-brain-frontend party-brain-backend"
echo ""
echo "如需清除数据卷（⚠️ 会删除所有数据）："
echo "  docker volume rm party-brain-data"
