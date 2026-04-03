import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import legacy from '@vitejs/plugin-legacy'

// 本地开发默认指向 localhost:8000
// Docker 容器内通过环境变量 VITE_API_TARGET 指向后端容器名
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [
    react(),
    legacy({
      targets: ['Chrome >= 63', 'Firefox >= 67', 'Safari >= 11.1'],
      additionalLegacyPolyfills: ['regenerator-runtime/runtime'],
      modernPolyfills: true,
    }),
  ],
  esbuild: {
    target: 'chrome69',
  },
  build: {
    target: 'es2015',
    cssTarget: 'chrome63',
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
})
