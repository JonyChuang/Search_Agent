import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// 求职业务使用 Java，其余 /api 路径继续使用 Comet。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '^/api/career(?:/|\\?|$)': {
        target: `http://127.0.0.1:${process.env.CAREER_BACKEND_PORT || '8080'}`,
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
