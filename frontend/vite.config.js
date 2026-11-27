import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // three.js ships as one lazy chunk (~245 kB gzipped) that loads only when a
    // 3D scene is on screen; it never blocks the first paint.
    chunkSizeWarningLimit: 1000,
  },
})
