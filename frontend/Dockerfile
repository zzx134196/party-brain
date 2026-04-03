# ---- 阶段1: 构建前端静态文件 ----
FROM node:18-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com

COPY . .
RUN npm run build

# ---- 阶段2: Nginx托管静态文件 ----
FROM nginx:1.25-alpine

# 移除默认配置
RUN rm /etc/nginx/conf.d/default.conf

# 复制自定义nginx配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制产物
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
