FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --engine-strict=false

COPY . .
RUN npm run build:app

FROM node:20-alpine

WORKDIR /app

RUN apk add --no-cache python3

ENV NODE_ENV=production \
    PORT=8787 \
    UKUMOG_ENGINE_ROOT=/app/vendor/ukumog-engine \
    UKUMOG_PYTHON=python3

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --engine-strict=false

COPY server.mjs game-core.mjs ./
COPY --from=build /app/site ./site
COPY --from=build /app/vendor/ukumog-engine ./vendor/ukumog-engine

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "const http=require('http');const req=http.get({host:'127.0.0.1',port:process.env.PORT||8787,path:'/health'},res=>process.exit(res.statusCode===200?0:1));req.on('error',()=>process.exit(1));req.setTimeout(3000,()=>{req.destroy();process.exit(1);});"

CMD ["node", "server.mjs"]
