# 第一阶段：构建前端
FROM public.ecr.aws/docker/library/node:26-bookworm-slim@sha256:add5c17c14752c54d2f3d519ec46a3815684d41c33f198bcb09fb998f7dcbf68 AS builder

WORKDIR /app
ARG VUE_APP_LOCAL_PREVIEW=false
ENV VUE_APP_LOCAL_PREVIEW=$VUE_APP_LOCAL_PREVIEW

# 复制 package 文件
COPY package.json package-lock.json ./
COPY layouts/ ./layouts/

# 安装依赖（npm ci 按 lockfile 精确安装，供应链更可控）
RUN --mount=type=cache,id=hoim-web-npm,target=/root/.npm,sharing=locked \
    npm ci --legacy-peer-deps --prefer-offline

# 复制源码并构建
COPY . .
RUN npm run build

# 第二阶段：使用 nginx  serve 静态文件
FROM public.ecr.aws/docker/library/nginx:1.31.8-alpine@sha256:713fc2ebfd92e8217db451477182ee91944b123d2b1ee9fd5a8c6e91ca6c3a11
RUN apk upgrade --no-cache

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
