# syntax=docker/dockerfile:1

# --- Dependencies (also the base of the development image) ---------------------------------------
FROM node:24.21.0-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

# --- Development: Vite dev server with hot reload (docker-compose.dev.yml) ------------------------
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# --- Build: type check and production bundle ---------------------------------------------------
FROM deps AS build
COPY . .
RUN npm run build

# --- Runtime: nginx serves the bundle and proxies /api to the backend ----------------------------
FROM nginx:1.30-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
