FROM node:22-alpine@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx/ /etc/nginx/sift/
COPY --from=build /app/dist /usr/share/nginx/html
# /var/run is a symlink to /run on Alpine; the pid file lives in /run.
RUN chown -R nginx:nginx /var/cache/nginx /run
USER nginx
# 8080 is published; 8081 is for the https profile's caddy only.
EXPOSE 8080 8081
