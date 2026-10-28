# 第一阶段：构建前端
FROM public.ecr.aws/docker/library/node:24-bookworm-slim@sha256:be8204d4bd327363357f532187b752ff62759c31bedf98e9e18fc08c9cbd605c AS builder

WORKDIR /app

# 复制 package 文件
COPY package.json package-lock.json ./

# 安装依赖（npm ci 按 lockfile 精确安装，供应链更可控）
RUN npm ci --legacy-peer-deps

# 复制源码并构建
COPY . .
RUN npm run build

# 第二阶段：使用 nginx  serve 静态文件
FROM public.ecr.aws/docker/library/nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951
RUN apk upgrade --no-cache

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
