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
      targets: ['Chrome >= 63', 'Firefox >= 60', 'Safari >= 11.1'],
      additionalLegacyPolyfills: ['regenerator-runtime/runtime'],
      modernPolyfills: [
        'es.promise',
        'es.promise.finally',
        'es.array.flat',
        'es.array.flat-map',
        'es.object.from-entries',
        'es.string.match-all',
        'es.global-this',
      ],
      renderLegacyChunks: true,
    }),
  ],
  esbuild: {
    target: 'es2015',
  },
  build: {
    target: 'es2015',
    cssTarget: 'chrome63',
    minify: 'terser',
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
