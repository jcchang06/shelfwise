import { NavLink, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { ErrorBoundary } from './ErrorBoundary';
import { ShelfBar } from './ShelfBar';

/** Layout for logged-in pages: skip link, navigation and the main landmark. */
export function AppShell() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="app-header">
        <nav aria-label="Main" className="app-nav">
          <NavLink to="/dashboard" className="brand">
            Shelfwise
          </NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/shelf">Shelf</NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/import">Import</NavLink>
        </nav>
        <div className="app-user">
          {user ? <span className="app-user-email">{user.email}</span> : null}
          <button type="button" className="button-secondary" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <ShelfBar />
      <main id="main" tabIndex={-1}>
        <ErrorBoundary resetKey={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
