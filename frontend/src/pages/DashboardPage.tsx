import { useAuth } from '../auth/AuthContext';

/** Placeholder until the dashboard PR adds quick logging and the stats charts. */
export default function DashboardPage() {
  const { user } = useAuth();
  return (
    <>
      <h1>Dashboard</h1>
      <p>Signed in as {user?.email}. Quick logging and your reading charts arrive next.</p>
    </>
  );
}
