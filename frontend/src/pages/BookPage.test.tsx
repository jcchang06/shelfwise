import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { setRefreshToken } from '../api/tokens';
import type { BookDetail, ShelfEntry } from '../api/types';
import { localDateISO } from '../dates';
import { bookDetail, page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

interface Captured {
  patches: Record<string, unknown>[];
  posts: Record<string, unknown>[];
  deletes: string[];
}

/**
 * Logged in on /books/42. GET returns `book` and `entry` (null = not on the shelf); PATCH
 * merges the body into the entry like the API would, unless `patchResponse` overrides it.
 */
function setup({
  book = bookDetail(),
  entry = null as ShelfEntry | null,
  patchResponse,
}: {
  book?: BookDetail | Response;
  entry?: ShelfEntry | null;
  patchResponse?: () => Response;
} = {}): Captured {
  setRefreshToken('refresh-1');
  const captured: Captured = { patches: [], posts: [], deletes: [] };
  let current = entry;
  server.use(
    ...authHandlers(),
    http.get(api('/books/42/'), () => (book instanceof Response ? book : HttpResponse.json(book))),
    http.get(api('/shelf/'), () => HttpResponse.json(page(current ? [current] : []))),
    http.patch(api('/shelf/7/'), async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      captured.patches.push(body);
      if (patchResponse) return patchResponse();
      if (!current) return HttpResponse.json({ detail: 'Not found.' }, { status: 404 });
      current = { ...current, ...body, updated_at: new Date().toISOString() } as ShelfEntry;
      return HttpResponse.json(current);
    }),
    http.post(api('/shelf/'), async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      captured.posts.push(body);
      current = shelfEntry({ status: body.status as ShelfEntry['status'] });
      return HttpResponse.json(current, { status: 201 });
    }),
    http.delete(api('/shelf/7/'), ({ request }) => {
      captured.deletes.push(request.url);
      current = null;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return captured;
}

const statusForm = () => screen.getByRole('form', { name: 'Status' });
const ratingForm = () => screen.getByRole('form', { name: 'Rating and review' });
const detailsForm = () => screen.getByRole('form', { name: 'Details' });

describe('book details', () => {
  it('shows the book', async () => {
    setup({ book: bookDetail({ series_name: 'Hail Mary', series_number: '2.0' }) });
    renderApp('/books/42');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Project Hail Mary' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Andy Weir · 2021 · 496 pages')).toBeInTheDocument();
    expect(screen.getByText('Series: Hail Mary #2')).toBeInTheDocument();
    expect(screen.getByText('Science Fiction, Thrillers')).toBeInTheDocument();
    expect(screen.getByText('A lone astronaut must save the earth.')).toBeInTheDocument();
    expect(screen.getByText('Except he can’t remember his name.')).toBeInTheDocument(); // own paragraph
    expect(screen.getByRole('link', { name: /view on google books/i })).toHaveAttribute(
      'href',
      'https://books.google.com/books?id=vol1',
    );
  });

  it('shows not found for an unknown book', async () => {
    setup({ book: HttpResponse.json({ detail: 'Not found.' }, { status: 404 }) });
    renderApp('/books/42');
    expect(await screen.findByRole('heading', { name: 'Book not found' })).toBeInTheDocument();
  });

  it('shows not found for a non-numeric id without a request', async () => {
    setup();
    renderApp('/books/abc');
    expect(await screen.findByRole('heading', { name: 'Book not found' })).toBeInTheDocument();
  });
});

describe('adding from the book page', () => {
  it('adds by book_id and then shows the shelf controls', async () => {
    const captured = setup();
    renderApp('/books/42');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Add' }));

    expect(await screen.findByRole('form', { name: 'Status' })).toBeInTheDocument();
    expect(captured.posts).toEqual([{ book_id: 42, status: 'want_to_read' }]);
    expect(screen.getByText('Added Project Hail Mary to Want to read.')).toBeInTheDocument();
  });
});

describe('status', () => {
  it('keeps Save disabled until the status changes', async () => {
    setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    await screen.findByRole('form', { name: 'Status' });
    expect(within(statusForm()).getByRole('button', { name: 'Save status' })).toBeDisabled();
  });

  it('marks finished with a finish date', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'finished');

    const date = within(statusForm()).getByLabelText('Finished on');
    expect(date).toHaveValue(localDateISO());
    await user.clear(date);
    await user.type(date, '2026-11-01');
    await user.click(within(statusForm()).getByRole('button', { name: 'Save status' }));

    await screen.findByText('Moved to Finished.');
    expect(captured.patches).toEqual([{ status: 'finished', finished_at: '2026-11-01' }]);
  });

  it('requires a DNF reason before sending anything', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'reading', pages_logged: 80 }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'dnf');
    await user.click(within(statusForm()).getByRole('button', { name: 'Save status' }));

    expect(screen.getByRole('combobox', { name: 'Why did you stop?' })).toHaveAccessibleDescription(
      'Choose why you stopped reading.',
    );
    expect(captured.patches).toHaveLength(0);
  });

  it('marks DNF with reason, the logged page (capped), date and note', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'reading', pages_logged: 600 }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'dnf');

    expect(screen.getByLabelText('Stopped at page')).toHaveValue(496); // capped at page_count
    await user.selectOptions(screen.getByRole('combobox', { name: 'Why did you stop?' }), 'pacing');
    await user.type(screen.getByLabelText('Note (optional)'), 'Too slow');
    await user.click(within(statusForm()).getByRole('button', { name: 'Save status' }));

    await screen.findByText('Moved to Did not finish.');
    expect(captured.patches).toEqual([
      {
        status: 'dnf',
        dnf_reason: 'pacing',
        dnf_page: 496,
        dnf_at: localDateISO(),
        dnf_note: 'Too slow',
      },
    ]);
  });

  it('explains that resuming clears DNF details, and sends only the status', async () => {
    const captured = setup({
      entry: shelfEntry({
        status: 'dnf',
        dnf_reason: 'pacing',
        dnf_page: 120,
        dnf_at: '2026-11-01',
      }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'reading');

    expect(screen.getByText(/Resuming clears the DNF details/)).toBeInTheDocument();
    await user.click(within(statusForm()).getByRole('button', { name: 'Save status' }));
    await screen.findByText('Moved to Reading.');
    expect(captured.patches).toEqual([{ status: 'reading' }]);
  });

  it('explains a re-read when a finished book goes back to reading', async () => {
    setup({ entry: shelfEntry({ status: 'finished', rating: 5, finished_at: '2025-03-09' }) });
    renderApp('/books/42');
    await userEvent
      .setup()
      .selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'reading');
    expect(
      screen.getByText('Re-reading: your rating stays, and the start date becomes today.'),
    ).toBeInTheDocument();
  });

  it('shows API rule errors', async () => {
    setup({
      entry: shelfEntry({ status: 'reading' }),
      patchResponse: () =>
        HttpResponse.json({ finished_at: ["This date can't be in the future."] }, { status: 400 }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Shelf' }), 'finished');
    await user.click(within(statusForm()).getByRole('button', { name: 'Save status' }));

    await waitFor(() =>
      expect(within(statusForm()).getByLabelText('Finished on')).toHaveAccessibleDescription(
        "This date can't be in the future.",
      ),
    );
  });
});

describe('rating and review', () => {
  it('rates a finished book with the keyboard-friendly radio group', async () => {
    const captured = setup({
      entry: shelfEntry({ status: 'finished', finished_at: '2026-11-01' }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Rating and review' });

    const group = within(ratingForm()).getByRole('group', { name: 'Your rating' });
    expect(within(group).getAllByRole('radio')).toHaveLength(5);
    await user.click(within(group).getByRole('radio', { name: '4 stars' }));
    await user.click(within(ratingForm()).getByRole('button', { name: 'Save rating and review' }));

    await screen.findByText('Saved your rating and review.');
    expect(captured.patches).toEqual([{ rating: 4 }]);
  });

  it('moves between stars with arrow keys', async () => {
    setup({ entry: shelfEntry({ status: 'finished', rating: 2, finished_at: '2026-11-01' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Rating and review' });
    const two = screen.getByRole('radio', { name: '2 stars' });
    two.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: '3 stars' })).toBeChecked();
  });

  it('clears a rating and saves a review', async () => {
    const captured = setup({
      entry: shelfEntry({ status: 'finished', rating: 3, finished_at: '2026-11-01' }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Rating and review' });
    await user.click(within(ratingForm()).getByRole('button', { name: 'Clear' }));
    await user.type(within(ratingForm()).getByLabelText('Review'), 'Loved it');
    await user.click(within(ratingForm()).getByRole('button', { name: 'Save rating and review' }));

    await screen.findByText('Saved your rating and review.');
    expect(captured.patches).toEqual([{ rating: null, review: 'Loved it' }]);
  });

  it('shows a kept rating read-only during a re-read', async () => {
    setup({ entry: shelfEntry({ status: 'reading', rating: 5, finished_at: '2025-03-09' }) });
    renderApp('/books/42');
    await screen.findByRole('form', { name: 'Rating and review' });
    expect(within(ratingForm()).queryByRole('radio')).not.toBeInTheDocument();
    expect(within(ratingForm()).getByText(/kept from your last read/)).toBeInTheDocument();
    expect(within(ratingForm()).getByRole('img', { name: '5 out of 5 stars' })).toBeInTheDocument();
  });

  it('explains when a book can be rated', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'want_to_read' }) });
    renderApp('/books/42');
    await screen.findByRole('form', { name: 'Rating and review' });
    expect(screen.getByText("You can rate this book once it's finished.")).toBeInTheDocument();

    // Reviews work on any status.
    const user = userEvent.setup();
    await user.type(within(ratingForm()).getByLabelText('Review'), 'Heard great things');
    await user.click(within(ratingForm()).getByRole('button', { name: 'Save rating and review' }));
    await screen.findByText('Saved your rating and review.');
    expect(captured.patches).toEqual([{ review: 'Heard great things' }]);
  });
});

describe('details', () => {
  it('sends only the changed dates, with a cleared date as null', async () => {
    const captured = setup({
      entry: shelfEntry({
        status: 'finished',
        started_at: '2026-10-01',
        finished_at: '2026-10-20',
      }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Details' });
    await user.clear(within(detailsForm()).getByLabelText('Started on'));
    await user.click(within(detailsForm()).getByRole('button', { name: 'Save details' }));

    await screen.findByText('Saved the details.');
    expect(captured.patches).toEqual([{ started_at: null }]);
  });

  it('edits DNF details while the book is DNF', async () => {
    const captured = setup({
      entry: shelfEntry({
        status: 'dnf',
        dnf_reason: 'pacing',
        dnf_page: 120,
        dnf_at: '2026-11-01',
      }),
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Details' });
    await user.selectOptions(
      within(detailsForm()).getByRole('combobox', { name: 'Why did you stop?' }),
      'not_my_genre',
    );
    await user.click(within(detailsForm()).getByRole('button', { name: 'Save details' }));

    await screen.findByText('Saved the details.');
    expect(captured.patches).toEqual([{ dnf_reason: 'not_my_genre' }]);
  });

  it('has no DNF fields for other statuses', async () => {
    setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    await screen.findByRole('form', { name: 'Details' });
    expect(within(detailsForm()).queryByLabelText('Why did you stop?')).not.toBeInTheDocument();
  });
});

describe('removing', () => {
  it('confirms with the log count, then removes and returns to the shelf', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'reading', reading_log_count: 12 }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Remove from shelf' }));

    const dialog = screen.getByRole('dialog', {
      name: 'Remove Project Hail Mary from your shelf?',
    });
    expect(dialog).toHaveTextContent('This also deletes your 12 reading logs for this book.');
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus();

    await user.click(within(dialog).getByRole('button', { name: 'Remove' }));

    expect(await screen.findByRole('heading', { name: 'Your shelf' })).toBeInTheDocument();
    expect(screen.getByText('Removed Project Hail Mary from your shelf.')).toBeInTheDocument();
    expect(captured.deletes).toHaveLength(1);
  });

  it('cancelling sends nothing', async () => {
    const captured = setup({ entry: shelfEntry({ status: 'reading', reading_log_count: 1 }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Remove from shelf' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('your 1 reading log for this book');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(captured.deletes).toHaveLength(0);
  });
});
