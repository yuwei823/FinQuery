import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { resolve } from "node:path"

const staticDirectoryPages = new Set(["/workflow", "/dev_resume"])

export default defineConfig({
  plugins: [
    vue(),
    {
      name: "static-directory-pages",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const [pathname, query = ""] = (request.url ?? "").split("?", 2)
          if (staticDirectoryPages.has(pathname)) {
            response.statusCode = 308
            response.setHeader("Location", `${pathname}/${query ? `?${query}` : ""}`)
            response.end()
            return
          }
          const directoryPath = pathname.endsWith("/") ? pathname.slice(0, -1) : ""
          if (staticDirectoryPages.has(directoryPath)) {
            request.url = `${directoryPath}/index.html${query ? `?${query}` : ""}`
          }
          next()
        })
      },
    },
  ],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        workflow: resolve(__dirname, "workflow/index.html"),
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      usePolling: true,
      interval: 3000,
    },
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
})
