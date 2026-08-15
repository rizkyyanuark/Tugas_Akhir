FROM node:22-alpine AS development
WORKDIR /app
RUN npm install -g pnpm@10.11.0

COPY ./web/package*.json ./
COPY ./web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./web .
EXPOSE 5173

FROM node:22-alpine AS build-stage
WORKDIR /app
RUN npm install -g pnpm@10.11.0

COPY ./web/package*.json ./
COPY ./web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY ./web .
RUN pnpm run build

FROM nginx:alpine AS production
COPY --from=build-stage /app/dist /usr/share/nginx/html
COPY ./docker/nginx/nginx.conf /etc/nginx/nginx.conf
COPY ./docker/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
