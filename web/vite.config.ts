import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  server: {
    host: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  plugins: [
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "Sift Lab",
        short_name: "Sift",
        description: "Food-fraud screening tests run with your phone.",
        theme_color: "#15231E",
        background_color: "#EEF1EE",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: "/index.html",
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/v1/assays"),
            handler: "StaleWhileRevalidate",
            options: { cacheName: "assays" },
          },
          {
            urlPattern: ({ url }) => url.origin.includes("fonts."),
            handler: "CacheFirst",
            options: { cacheName: "fonts" },
          },
        ],
      },
    }),
  ],
});
