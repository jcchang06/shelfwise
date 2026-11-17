import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';

import { fieldErrors, formError, type FieldErrors } from '../api/errors';
import { useAuth } from '../auth/AuthContext';
import type { LoginLocationState } from '../auth/RequireAuth';
import { FormField } from '../components/FormField';

export default function LoginPage() {
  const { status, login, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LoginLocationState | null)?.from ?? '/dashboard';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [summary, setSummary] = useState<string | null>(null);

  if (status === 'authenticated') return <Navigate to={from} replace />;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrors({});
    setSummary(null);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (error) {
      setErrors(fieldErrors(error));
      setSummary(formError(error) ?? 'Please fix the highlighted fields.');
      setSubmitting(false);
    }
  }

  return (
    <main id="main" className="auth-page">
      <h1>Log in to Shelfwise</h1>
      {sessionExpired && !summary ? (
        <p className="notice" role="status">
          Your session expired. Please log in again.
        </p>
      ) : null}
      {summary ? (
        <p className="error-summary" role="alert">
          {summary}
        </p>
      ) : null}
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={errors.email}
        />
        <FormField
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? 'Logging in…' : 'Log in'}
        </button>
      </form>
    </main>
  );
}
