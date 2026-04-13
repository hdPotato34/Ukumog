FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./

# 🔧 修复：设置国内镜像源 + 跳过 electron 下载脚本 + 忽略引擎版本检查
ENV ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
RUN npm ci --ignore-scripts --engine-strict=false

COPY . .
RUN npm run build:app

# ---------- 生产阶段 ----------
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
COPY server.mjs game-core.mjs ./
COPY --from=build /app/site ./site

# 🔧 修复：生产环境安装也加镜像源（防止后续手动 npm install 出问题）
ENV NODE_ENV=production \
    PORT=8787 \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com

# 生产依赖安装时也跳过脚本（如果 package.json 有 postinstall）
RUN npm ci --omit=dev --ignore-scripts --engine-strict=false

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "const http=require('http');const req=http.get({host:'127.0.0.1',port:process.env.PORT||8787,path:'/health'},res=>process.exit(res.statusCode===200?0:1));req.on('error',()=>process.exit(1));req.setTimeout(3000,()=>{req.destroy();process.exit(1);});"

CMD ["node", "server.mjs"]