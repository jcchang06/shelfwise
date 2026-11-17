import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ErrorBoundary } from './ErrorBoundary';

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error('kaboom');
  return <p>All good</p>;
}

describe('ErrorBoundary', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows "Something went wrong" with Reload and logs the error', async () => {
    const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const reload = vi.fn();
    render(
      <ErrorBoundary onReload={reload}>
        <Boom explode />
      </ErrorBoundary>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Reload' }));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(logged).toHaveBeenCalledWith(
      'Shelfwise: a page crashed.',
      expect.objectContaining({ message: 'kaboom' }),
      expect.any(String),
    );
  });

  it('gives the page another try when the reset key changes', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { rerender } = render(
      <ErrorBoundary resetKey="/shelf">
        <Boom explode />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="/dashboard">
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('All good')).toBeInTheDocument();
  });
});
