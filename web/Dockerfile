FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS build
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
