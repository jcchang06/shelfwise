import { Navigate, Route, Routes } from 'react-router-dom';

import { RequireAuth } from './auth/RequireAuth';
import { AppShell } from './components/AppShell';
import { ServerWakingBanner } from './components/ServerWakingBanner';
import BookPage from './pages/BookPage';
import DashboardPage from './pages/DashboardPage';
import LoginPage from './pages/LoginPage';
import NotFoundPage from './pages/NotFoundPage';
import SearchPage from './pages/SearchPage';
import ShelfPage from './pages/ShelfPage';

export default function App() {
  return (
    <>
      {/* Outside the routes so it also shows on /login during a cold start. */}
      <ServerWakingBanner />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/shelf" element={<ShelfPage />} />
            <Route path="/books/:id" element={<BookPage />} />
          </Route>
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </>
  );
}
