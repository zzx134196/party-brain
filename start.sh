#!/bin/bash
# 智慧党建助手 - 一键启动脚本

cd "$(dirname "$0")"

echo "🚀 智慧党建助手 启动中..."

# 杀掉已有进程
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null
sleep 1

# 启动后端
echo "📦 启动后端 (端口8000)..."
cd backend
python3.11 -m uvicorn app.main:app --port 8000 &
BACKEND_PID=$!
cd ..

# 等后端就绪
sleep 3

# 启动前端
echo "🎨 启动前端 (端口3000)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

sleep 2

echo ""
echo "✅ 启动完成！"
echo "================================"
echo "  前端界面: http://localhost:3000"
echo "  API文档:  http://localhost:8000/docs"
echo "  账号:     admin / admin123"
echo "================================"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号，停止所有子进程
trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
