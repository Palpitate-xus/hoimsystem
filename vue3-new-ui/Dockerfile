# 第一阶段：构建前端
FROM public.ecr.aws/docker/library/node:26-bookworm-slim@sha256:bc0a2afd3b74ce12222fc8bab99271e66257f021078f5f4a5d687a77d280c1d9 AS builder

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
FROM public.ecr.aws/docker/library/nginx:1.30.6-alpine@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949
RUN apk upgrade --no-cache

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
