import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/ws': {
        target: 'ws://127.0.0.1:8080',
        ws: true,
      },
      '/upload': 'http://127.0.0.1:8080',
      '/uploads': 'http://127.0.0.1:8080',
      '/raw-file': 'http://127.0.0.1:8080',
      '/api': 'http://127.0.0.1:8080',
    }
  }
})
