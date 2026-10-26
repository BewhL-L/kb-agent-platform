# ====== 第一阶段：构建前端 ======
FROM node:20-alpine AS builder

WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存层
COPY package.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install --legacy-peer-deps

# 复制源码并构建（跳过严格类型检查，避免构建中断）
COPY . .
RUN npm run build:no-check

# ====== 第二阶段：Nginx 托管静态文件 ======
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置（前端静态托管 + API 反向代理）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
