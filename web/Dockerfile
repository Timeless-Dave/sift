FROM node:26-alpine@sha256:6bd9ab43c0ec0190ca7b2d193906cb8b7edf6e7f4afa43ddeccd6452710bffb5 AS build
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
