# ==============================================================================
# Frontend — Unified Dockerfile
# ==============================================================================
# Two build targets:
#   development  — node image, source bind-mounted, Vite HMR
#   production   — multi-stage: node builder → nginx static server
#
# docker-compose.yml      uses  target: production
# docker-compose.dev.yml  uses  target: development
# ==============================================================================

ARG NODE_VERSION=24

# ── Shared base: node + native build tools (Debian-based) ────────────────────
FROM node:${NODE_VERSION} AS base
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ── Development ──────────────────────────────────────────────────────────────
# Source is bind-mounted, node_modules in a named volume.
FROM base AS development
EXPOSE 5173
CMD ["sh", "-c", "npm install && npm run dev -- --host 0.0.0.0 --port 5173"]

# ── Production builder: compile static assets ────────────────────────────────
FROM base AS builder
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# ── Production: nginx serving compiled static files ──────────────────────────
FROM nginx:1.25-alpine AS production
RUN apk add --no-cache curl
RUN rm -rf /usr/share/nginx/html/* /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
RUN addgroup -g 101 -S nginx && \
    adduser -S -D -H -u 101 -h /var/cache/nginx -s /sbin/nologin -G nginx -g nginx nginx 2>/dev/null || true
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid
USER nginx
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:80/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
