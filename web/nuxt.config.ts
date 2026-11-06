export default defineNuxtConfig({
  srcDir: "app",
  ssr: false,
  modules: ["@nuxt/ui"],
  css: ["~/assets/css/main.css"],
  compatibilityDate: "2026-04-11",
  devServer: {
    port: 3000,
  },
  app: {
    head: {
      title: "Shinban Sync",
      htmlAttrs: { lang: "zh-CN" },
      link: [{ rel: "icon", type: "image/png", href: "/icon.png" }],
    },
  },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: "http://127.0.0.1:3325",
          changeOrigin: true,
        },
      },
    },
  },
})
