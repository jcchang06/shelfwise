/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  // Read VITE_* variables from the repo-root .env shared with the backend.
  envDir: '..',
  server: {
    host: true, // listen on 0.0.0.0 so the docker-compose port mapping works
    port: 5173,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
