import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { createQueryClient } from './api/queryClient';
import App from './App';
import { AuthProvider } from './auth/AuthProvider';
import './index.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error('Missing #root element in index.html');
}

const queryClient = createQueryClient();

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
