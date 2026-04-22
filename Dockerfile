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

RUN apk add --no-cache python3 py3-pip py3-virtualenv

COPY package.json package-lock.json ./
COPY server.mjs game-core.mjs ./
COPY --from=build /app/site ./site
COPY model-server/requirements-serving.txt ./model-server/requirements-serving.txt
COPY model-server/src/serving ./model-server/src/serving
COPY ukumog-engine ./ukumog-engine
COPY docker/start-services.sh /usr/local/bin/start-services.sh
COPY docker/healthcheck.sh /usr/local/bin/healthcheck.sh

# 🔧 修复：生产环境安装也加镜像源（防止后续手动 npm install 出问题）
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8787 \
    UKUMOG_HOST=127.0.0.1 \
    UKUMOG_PORT=8011 \
    ENGINE_SERVICE_ORIGIN=http://127.0.0.1:8011 \
    ENGINE_SERVICE_TIMEOUT_MS=15000 \
    NPM_CONFIG_REGISTRY=https://registry.npmmirror.com \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
    PIP_DEFAULT_TIMEOUT=120 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/ukumog-venv \
    PATH=/opt/ukumog-venv/bin:$PATH

# 生产依赖安装时也跳过脚本（如果 package.json 有 postinstall）
RUN npm ci --omit=dev --ignore-scripts --engine-strict=false
RUN python3 -m venv "$VIRTUAL_ENV" \
 && python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir -r model-server/requirements-serving.txt
RUN python -m pip install --no-cache-dir ./ukumog-engine \
 && chmod +x /usr/local/bin/start-services.sh /usr/local/bin/healthcheck.sh

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD /usr/local/bin/healthcheck.sh

CMD ["/usr/local/bin/start-services.sh"]
