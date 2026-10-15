import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // xfwd: 转发时补上 X-Forwarded-For，后端据此判断是否为非本机访问
      '/api': { target: 'http://127.0.0.1:8787', xfwd: true },
      '/ws': {
        target: 'ws://127.0.0.1:8787',
        ws: true,
        xfwd: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
