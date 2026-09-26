import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(() => {
  const backendOrigin = process.env.LINAR_BACKEND_ORIGIN || 'http://127.0.0.1:8080'
  const backendWsOrigin = backendOrigin.replace(/^http/, 'ws')
  const guiHost = process.env.LINAR_GUI_HOST || '127.0.0.1'
  const guiPort = Number(process.env.LINAR_GUI_PORT || 5173)

  return {
    plugins: [vue()],
    server: {
      host: guiHost,
      port: guiPort,
      strictPort: true,
      proxy: {
        '/ws': {
          target: backendWsOrigin,
          ws: true,
        },
        '/upload': backendOrigin,
        '/uploads': backendOrigin,
        '/raw-file': backendOrigin,
        '/api': backendOrigin,
      }
    }
  }
})
