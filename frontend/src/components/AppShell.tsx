import { NavLink, Outlet } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';

/** Layout for logged-in pages: skip link, navigation and the main landmark. */
export function AppShell() {
  const { user, logout } = useAuth();
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
          <NavLink to="/search">Search</NavLink>
        </nav>
        <div className="app-user">
          {user ? <span className="app-user-email">{user.email}</span> : null}
          <button type="button" className="button-secondary" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}
