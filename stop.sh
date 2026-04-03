#!/bin/bash
# 智慧党建助手 - 停止所有服务
echo "正在停止服务..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:3000 | xargs kill -9 2>/dev/null
echo "✅ 所有服务已停止"
