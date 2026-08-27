import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(() => {
  const backendOrigin = process.env.LINAR_BACKEND_ORIGIN || 'http://127.0.0.1:8080'
  const backendWsOrigin = backendOrigin.replace(/^http/, 'ws')

  return {
    plugins: [vue()],
    server: {
      port: 5173,
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
