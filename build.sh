#!/bin/bash
# 智慧党建助手 - 本地构建镜像并导出为压缩包（用于离线部署到客户服务器）
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$PROJECT_DIR/docker-images"

echo "🔨 开始构建镜像..."
mkdir -p "$OUTPUT_DIR"

# 构建后端镜像
echo "📦 构建后端镜像 party-brain-backend..."
docker build -t party-brain-backend:latest "$PROJECT_DIR/backend"

# 构建前端镜像
echo "🎨 构建前端镜像 party-brain-frontend..."
docker build -t party-brain-frontend:latest "$PROJECT_DIR/frontend"

echo ""
echo "⬇️  拉取依赖镜像..."
docker pull mysql:8.0
docker pull bitnami/etcd:3.5.5
docker pull minio/minio:RELEASE.2023-03-20T20-16-18Z
docker pull milvusdb/milvus:v2.3.3

echo ""
echo "💾 导出所有镜像为压缩包..."
docker save \
  party-brain-backend:latest \
  party-brain-frontend:latest \
  mysql:8.0 \
  bitnami/etcd:3.5.5 \
  minio/minio:RELEASE.2023-03-20T20-16-18Z \
  milvusdb/milvus:v2.3.3 \
  | gzip > "$OUTPUT_DIR/party-brain-images.tar.gz"

echo ""
echo "✅ 构建完成！"
echo "================================"
echo "  镜像包: $OUTPUT_DIR/party-brain-images.tar.gz"
echo "  大小: $(du -sh $OUTPUT_DIR/party-brain-images.tar.gz | cut -f1)"
echo ""
echo "📤 将以下文件传输到客户服务器："
echo "  1. $OUTPUT_DIR/party-brain-images.tar.gz"
echo "  2. $PROJECT_DIR/deploy.sh"
echo "  3. $PROJECT_DIR/backend/.env.docker"
echo "================================"
