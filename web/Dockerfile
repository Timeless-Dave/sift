FROM node:22-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/ /etc/nginx/sift/
COPY --from=build /app/dist /usr/share/nginx/html
# /var/run is a symlink to /run on Alpine; the pid file lives in /run.
RUN chown -R nginx:nginx /var/cache/nginx /run
USER nginx
# 8080 is published; 8081 is for the https profile's caddy only.
EXPOSE 8080 8081
