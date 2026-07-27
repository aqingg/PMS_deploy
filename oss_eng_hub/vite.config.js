import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

const appBase = '/oss_eng_hub/'

function vitePluginToolRedirectGuard() {
  const guardScript = `    <script type="text/javascript">
      if (window.self === window.top) {
        var segments = window.location.pathname.split('/').filter(Boolean);
        if (segments.length > 0) {
          var lastSegment = segments[segments.length - 1].toLowerCase();
          if (lastSegment === 'index.html' || lastSegment === 'index.htm') {
            segments.pop();
          }
        }
        if (segments.length > 0) {
          var toolPath = segments.pop();
          if (toolPath === 'OSS_Benchmark_database') {
            toolPath = 'OSS_BENCHMARK_DATABASE';
          }
          var basePath = '/' + segments.join('/');
          var cleanBasePath = basePath.endsWith('/') ? basePath : basePath + '/';
          window.location.replace(cleanBasePath + '#/' + toolPath);
        }
      }
    </script>`

  return {
    name: 'vite-plugin-tool-redirect-guard',

    // 1. 开发阶段拦截请求注入
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url.split('?')[0]
        let relativePath = url
        if (url.startsWith(appBase)) {
          relativePath = url.slice(appBase.length)
        }
        relativePath = relativePath.replace(/^\//, '')

        const segments = relativePath.split('/').filter(Boolean)
        if (segments.length > 0) {
          const toolFolder = segments[0]
          const publicDir = path.resolve('public')
          const toolDirPath = path.join(publicDir, toolFolder)

          if (fs.existsSync(toolDirPath) && fs.statSync(toolDirPath).isDirectory()) {
            const isHtml = segments[1] === 'index.html' || segments.length === 1 || (segments.length === 2 && segments[1] === '')
            if (isHtml) {
              const indexPath = path.join(toolDirPath, 'index.html')
              if (fs.existsSync(indexPath)) {
                let html = fs.readFileSync(indexPath, 'utf8')
                if (!html.includes('window.self === window.top')) {
                  html = html.replace(/<head>/i, `<head>\n${guardScript}`)
                }
                res.statusCode = 200
                res.setHeader('Content-Type', 'text/html')
                res.end(html)
                return
              }
            }
          }
        }
        next()
      })
    },

    // 2. 生产打包后自动后处理 dist 下的子工具
    closeBundle() {
      const distDir = path.resolve('dist')
      const publicDir = path.resolve('public')
      if (!fs.existsSync(distDir) || !fs.existsSync(publicDir)) return

      // 读取 public/ 下所有的文件夹作为已知的子工具列表
      const subtools = fs.readdirSync(publicDir).filter(file => {
        const p = path.join(publicDir, file)
        return fs.statSync(p).isDirectory()
      })

      for (const tool of subtools) {
        const distToolIndexHtml = path.join(distDir, tool, 'index.html')
        if (fs.existsSync(distToolIndexHtml)) {
          let html = fs.readFileSync(distToolIndexHtml, 'utf8')
          if (!html.includes('window.self === window.top')) {
            html = html.replace(/<head>/i, `<head>\n${guardScript}`)
            fs.writeFileSync(distToolIndexHtml, html, 'utf8')
            console.log(`\n[Vite Guard Plugin] Successfully injected redirect guard into ${path.relative(distDir, distToolIndexHtml)}`)
          }
        }
      }
    }
  }
}

export default defineConfig({
  plugins: [react(), vitePluginToolRedirectGuard()],
  base: appBase,
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(__dirname, 'index.html')
      }
    },
    outDir: 'dist'
  },
  server: {
    fs: {
      allow: ['.']
    }
  }
})