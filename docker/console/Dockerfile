# Aegion SOC Console — static SPA served by nginx with a server-side /v1 proxy.
# Build context = repository root (matches docker/dashboard + build_and_push_images.sh).
#   docker build -f docker/console/Dockerfile -t sentra/console .

# ---- Stage 1: build the Vite SPA ----
FROM node:22-alpine AS build
WORKDIR /app

# Install deps first for layer caching (explicit copies avoid host node_modules).
COPY web/console/package.json web/console/package-lock.json ./
RUN npm ci

# Copy only what the build needs (NOT node_modules / dist).
COPY web/console/index.html ./
COPY web/console/vite.config.ts ./
COPY web/console/tsconfig.json web/console/tsconfig.app.json web/console/tsconfig.node.json ./
COPY web/console/src ./src
COPY web/console/public ./public

# Production build is live-data (no mocks): VITE_DATA_SOURCE unset → real /v1.
RUN npm run build

# ---- Stage 2: serve via nginx ----
FROM nginx:1.27-alpine

# Public API Gateway base (WS-16) — MUST include the `/prod` stage. nginx does
# proxy_pass ${SENTRA_API_BASE}/v1/ → https://…/prod/v1/. x-api-key is injected
# by the proxy at runtime from the ECS secret SENTRA_API_KEY (never in browser).
ENV SENTRA_API_BASE="https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod"
ENV SENTRA_API_HOST="iw3limi4k7.execute-api.us-east-1.amazonaws.com"
# Only substitute our own vars so nginx runtime vars ($uri, $host) survive envsubst.
ENV NGINX_ENVSUBST_FILTER="SENTRA_"

COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/console/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://localhost:80/ || exit 1
