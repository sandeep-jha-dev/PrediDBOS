import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://backend:3001',
        changeOrigin: true,
      },
      '/app-ws': {
        target: 'ws://backend:3001',
        ws: true,
        rewrite: (path) => path.replace(/^\/app-ws/, '/ws'),
      },
    },
  },
});