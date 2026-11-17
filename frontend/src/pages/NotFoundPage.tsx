import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <main id="main" className="auth-page">
      <h1>Page not found</h1>
      <p>
        That page doesn&apos;t exist. <Link to="/dashboard">Go to your dashboard</Link>.
      </p>
    </main>
  );
}
