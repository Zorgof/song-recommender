import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In development the FastAPI backend runs on :8000; in Docker nginx does this proxying.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
