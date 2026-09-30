import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { existsSync, readdirSync } from "node:fs"
import { resolve } from "node:path"

// public 下所有含 index.html 的子目录自动成为静态目录页，新增页面无需改配置。
function publicDirectoryPages(): Set<string> {
  const publicDir = resolve(__dirname, "public")
  const pages = new Set<string>()
  for (const entry of readdirSync(publicDir, { withFileTypes: true })) {
    if (entry.isDirectory() && existsSync(resolve(publicDir, entry.name, "index.html"))) {
      pages.add(`/${entry.name}`)
    }
  }
  return pages
}
const staticDirectoryPages = publicDirectoryPages()

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
