FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS build
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
