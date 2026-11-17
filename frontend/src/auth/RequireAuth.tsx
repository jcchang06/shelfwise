import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from './AuthContext';

export interface LoginLocationState {
  from?: string;
}

/** Protected routes: wait for a stored session to be checked, else go to /login and back. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'checking') {
    return (
      <p className="page-status" role="status">
        Loading your shelf…
      </p>
    );
  }
  if (status === 'anonymous') {
    const state: LoginLocationState = { from: location.pathname + location.search };
    return <Navigate to="/login" replace state={state} />;
  }
  return <Outlet />;
}
