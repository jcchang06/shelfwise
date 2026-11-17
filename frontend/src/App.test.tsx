import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SLOW_REQUEST_MS } from './api/serverWaking';
import { getRefreshToken, setRefreshToken } from './api/tokens';
import { renderApp } from './test/renderApp';
import { api, authHandlers, ME, server } from './test/server';

async function logIn(email = ME.email, password = 'correct-horse') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Email'), email);
  await user.type(screen.getByLabelText('Password'), password);
  await user.click(screen.getByRole('button', { name: 'Log in' }));
  return user;
}

describe('routing and login', () => {
  it('sends logged-out visitors to /login', async () => {
    renderApp('/dashboard');
    expect(await screen.findByRole('heading', { name: 'Log in to Shelfwise' })).toBeInTheDocument();
  });

  it('logs in and returns to the page that was asked for', async () => {
    server.use(...authHandlers());
    renderApp('/dashboard');
    await screen.findByRole('heading', { name: 'Log in to Shelfwise' });

    await logIn();

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.getByText(/signed in as reader@example.com/i)).toBeInTheDocument();
    expect(getRefreshToken()).toBe('refresh-1');
  });

  it('shows the server message for wrong credentials', async () => {
    server.use(
      http.post(api('/auth/token/'), () =>
        HttpResponse.json(
          { detail: 'No active account found with the given credentials' },
          { status: 401 },
        ),
      ),
    );
    renderApp('/login');
    await logIn('reader@example.com', 'wrong');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No active account found with the given credentials',
    );
  });

  it('shows field errors next to their inputs', async () => {
    server.use(
      http.post(api('/auth/token/'), () =>
        HttpResponse.json({ email: ['Enter a valid email address.'] }, { status: 400 }),
      ),
    );
    renderApp('/login');
    await logIn('nope', 'pw');

    const email = screen.getByLabelText('Email');
    await waitFor(() => expect(email).toHaveAttribute('aria-invalid', 'true'));
    expect(email).toHaveAccessibleDescription('Enter a valid email address.');
    expect(screen.getByRole('alert')).toHaveTextContent(/fix the highlighted fields/i);
  });

  it('restores a stored session on load', async () => {
    setRefreshToken('refresh-1');
    server.use(...authHandlers());
    renderApp('/dashboard');
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(getRefreshToken()).toBe('refresh-2'); // rotated on refresh
  });

  it('explains an expired session on the login page', async () => {
    setRefreshToken('refresh-old');
    server.use(
      http.post(api('/auth/token/refresh/'), () =>
        HttpResponse.json({ detail: 'Token is invalid or expired' }, { status: 401 }),
      ),
      http.get(api('/auth/me/'), () => HttpResponse.json({}, { status: 401 })),
    );
    renderApp('/dashboard');
    expect(
      await screen.findByText('Your session expired. Please log in again.'),
    ).toBeInTheDocument();
    expect(getRefreshToken()).toBeNull();
  });

  it('logs out', async () => {
    setRefreshToken('refresh-1');
    server.use(...authHandlers());
    renderApp('/dashboard');
    await screen.findByRole('heading', { name: 'Dashboard' });

    await userEvent.setup().click(screen.getByRole('button', { name: 'Log out' }));

    expect(await screen.findByRole('heading', { name: 'Log in to Shelfwise' })).toBeInTheDocument();
    expect(getRefreshToken()).toBeNull();
    expect(screen.queryByText(/session expired/i)).not.toBeInTheDocument();
  });

  it('shows a not-found page for unknown routes', () => {
    renderApp('/nope');
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('has a skip link to the main content', async () => {
    setRefreshToken('refresh-1');
    server.use(...authHandlers());
    renderApp('/dashboard');
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
  });
});

describe('cold-start banner', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('appears on the login page while a request is slow, then disappears', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server.use(
      http.post(api('/auth/token/'), async () => {
        await delay(SLOW_REQUEST_MS + 2000);
        return HttpResponse.json({ access: 'a', refresh: 'r' });
      }),
      http.get(api('/auth/me/'), () => HttpResponse.json(ME)),
    );
    renderApp('/login');
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(screen.getByLabelText('Email'), ME.email);
    await user.type(screen.getByLabelText('Password'), 'pw');
    await user.click(screen.getByRole('button', { name: 'Log in' }));

    expect(screen.queryByText(/waking up the server/i)).not.toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(SLOW_REQUEST_MS));
    expect(screen.getByText(/waking up the server/i)).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(2500));
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(screen.queryByText(/waking up the server/i)).not.toBeInTheDocument();
  });

  it('appears while a stored session is being restored', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setRefreshToken('refresh-1');
    server.use(
      http.post(api('/auth/token/refresh/'), async () => {
        await delay(SLOW_REQUEST_MS + 1000);
        return HttpResponse.json({ access: 'a', refresh: 'r' });
      }),
      http.get(api('/auth/me/'), () => HttpResponse.json(ME)),
    );
    renderApp('/dashboard');
    await act(() => vi.advanceTimersByTimeAsync(SLOW_REQUEST_MS));
    expect(screen.getByText(/waking up the server/i)).toBeInTheDocument();
    expect(screen.getByText('Loading your shelf…')).toBeInTheDocument();
  });
});
