/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type Plugin } from 'vite';

import { checkApiBaseUrl } from './build/apiBaseUrl';

// VITE_* variables come from env files in the *repo root* (shared with the backend), not
// frontend/. Precedence, highest first: variables already in the shell (including inline
// `VAR=... npm run dev`), then .env.[mode].local, .env.[mode], .env.local, .env.
// See README → "Frontend development".
const ENV_DIR = '..';

/** Prints which API the dev server talks to, so a stray shell variable can't hide. */
function announceApiBaseUrl(url: string | undefined): Plugin {
  return {
    name: 'shelfwise:announce-api-base-url',
    configureServer(server) {
      server.httpServer?.once('listening', () => {
        server.config.logger.info(
          `  ➜  API:     ${url ?? 'http://localhost:8000/api (VITE_API_BASE_URL not set)'}`,
        );
      });
    },
  };
}

export default defineConfig(({ command, mode }) => {
  // loadEnv also picks up VITE_* variables from the shell, which win over files.
  const apiBaseUrl = loadEnv(mode, ENV_DIR, 'VITE_').VITE_API_BASE_URL;

  if (command === 'build') {
    const problem = checkApiBaseUrl(apiBaseUrl, mode);
    if (problem) throw new Error(problem);
  }

  return {
    plugins: [react(), announceApiBaseUrl(apiBaseUrl)],
    envDir: ENV_DIR,
    server: {
      host: true, // listen on 0.0.0.0 so the docker-compose port mapping works
      port: 5173,
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
    },
  };
});
