# ══════════════════════════════════════════════════════════════
# web.Dockerfile — Vue SPA (Yuxi-style multi-stage)
# ══════════════════════════════════════════════════════════════
# Stages:
#   development — pnpm dev server with hot-reload
#   build-stage — compile production assets
#   production  — nginx serving static files + API reverse proxy
# ══════════════════════════════════════════════════════════════

# ─── DEVELOPMENT ────────────────────────────────────────────
FROM node:20-alpine AS development
WORKDIR /app
RUN npm install -g pnpm@latest

COPY ./web/package*.json ./
COPY ./web/pnpm-lock.yaml* ./
RUN pnpm install

COPY ./web .
EXPOSE 5173

# ─── BUILD (production assets) ──────────────────────────────
FROM node:20-alpine AS build-stage
WORKDIR /app
RUN npm install -g pnpm@latest

COPY ./web/package*.json ./
COPY ./web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

COPY ./web .
RUN pnpm run build

# ─── PRODUCTION (nginx) ────────────────────────────────────
FROM nginx:alpine AS production
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY ./docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY ./docker/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
