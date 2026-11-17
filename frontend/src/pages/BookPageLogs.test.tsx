/** Reading logs on the book page (T-3). The API's rules are mimicked by the handlers. */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type { ReadingLog } from '../api/logs';
import { setRefreshToken } from '../api/tokens';
import type { ShelfEntry } from '../api/types';
import { localDateISO } from '../dates';
import { bookDetail, page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

function logRow(overrides: Partial<ReadingLog> = {}): ReadingLog {
  return {
    id: 1,
    book_id: 42,
    log_date: '2026-11-03',
    pages_read: 30,
    created_at: '2026-11-03T20:00:00Z',
    updated_at: '2026-11-03T20:00:00Z',
    ...overrides,
  };
}

interface Api {
  posts: Record<string, unknown>[];
  patches: { id: string; body: Record<string, unknown> }[];
  deletes: string[];
}

/** A tiny in-memory version of the logs API, with the same-day and taken-day rules. */
function setup({ entry, logs = [] }: { entry: ShelfEntry; logs?: ReadingLog[] }): Api {
  setRefreshToken('refresh-1');
  const calls: Api = { posts: [], patches: [], deletes: [] };
  let current = entry;
  let rows = [...logs];
  let nextId = 100;
  const shelfFields = () => ({
    id: current.id,
    status: current.status,
    started_at: current.started_at,
    pages_logged: rows.reduce((sum, r) => sum + r.pages_read, 0),
  });

  server.use(
    ...authHandlers(),
    http.get(api('/books/42/'), () => HttpResponse.json(bookDetail())),
    http.get(api('/shelf/'), () =>
      HttpResponse.json(page([{ ...current, ...shelfFields(), reading_log_count: rows.length }])),
    ),
    http.get(api('/logs/'), () =>
      HttpResponse.json(page([...rows].sort((a, b) => b.log_date.localeCompare(a.log_date)))),
    ),
    http.post(api('/logs/'), async ({ request }) => {
      const body = (await request.json()) as { pages_read: number; log_date?: string };
      calls.posts.push(body);
      const day = body.log_date ?? localDateISO();
      let row = rows.find((r) => r.log_date === day);
      if (row) {
        row.pages_read += body.pages_read; // same day: adds
      } else {
        row = logRow({ id: nextId++, log_date: day, pages_read: body.pages_read });
        rows.push(row);
      }
      if (current.status === 'want_to_read') {
        current = { ...current, status: 'reading', started_at: current.started_at ?? day };
      }
      return HttpResponse.json({ ...row, shelf_entry: shelfFields() }, { status: 201 });
    }),
    http.patch(api('/logs/:id/'), async ({ request, params }) => {
      const body = (await request.json()) as { pages_read?: number; log_date?: string };
      calls.patches.push({ id: String(params.id), body });
      const row = rows.find((r) => String(r.id) === params.id);
      if (!row) return HttpResponse.json({ detail: 'Not found.' }, { status: 404 });
      const taken = body.log_date && rows.find((r) => r.log_date === body.log_date && r !== row);
      if (taken) {
        return HttpResponse.json(
          {
            log_date: [`You already logged this book on ${body.log_date}. Edit that day instead.`],
            conflict_id: taken.id,
          },
          { status: 400 },
        );
      }
      Object.assign(row, body);
      return HttpResponse.json({ ...row, shelf_entry: shelfFields() });
    }),
    http.delete(api('/logs/:id/'), ({ params }) => {
      calls.deletes.push(String(params.id));
      rows = rows.filter((r) => String(r.id) !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return calls;
}

const logForm = () => screen.getByRole('form', { name: 'Log pages' });
const logList = () => screen.getByRole('list', { name: 'Reading log' });

describe('logging pages', () => {
  it('logs today by default', async () => {
    const calls = setup({ entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    expect(within(logForm()).getByLabelText('Date (optional)')).toHaveValue(localDateISO());

    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '25');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    expect(await screen.findByText(/^Logged 25 pages for /)).toBeInTheDocument();
    expect(calls.posts).toEqual([{ book_id: 42, pages_read: 25, log_date: localDateISO() }]);
    expect(await within(logList()).findByText('25 pages')).toBeInTheDocument();
    expect(within(logForm()).getByLabelText('Pages read (required)')).toHaveValue(null); // cleared
  });

  it('adds to a day that already has a log', async () => {
    setup({
      entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }),
      logs: [logRow({ log_date: '2026-11-03', pages_read: 30 })],
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    const date = within(logForm()).getByLabelText('Date (optional)');
    await user.clear(date);
    await user.type(date, '2026-11-03');
    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '12');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    expect(await screen.findByText('Added 12 to Nov 3, 2026 (now 42 pages).')).toBeInTheDocument();
    expect(await within(logList()).findByText('42 pages')).toBeInTheDocument();
  });

  it('moves a want-to-read book to Reading and says so', async () => {
    setup({ entry: shelfEntry({ status: 'want_to_read' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '10');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    expect(await screen.findByText(/Moved to Reading\.$/)).toBeInTheDocument();
    const badge = await screen.findByText(
      (_, el) => el?.className === 'shelf-badge' && el.textContent === 'On your shelf · Reading',
    );
    expect(within(badge).getByRole('link', { name: 'Reading' })).toHaveAttribute(
      'href',
      '/shelf?status=reading',
    );
    // The status form re-keyed to the new status rather than showing a stale choice.
    expect(screen.getByRole('combobox', { name: 'Shelf' })).toHaveValue('reading');
  });

  it('updates reading progress', async () => {
    setup({
      entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }),
      logs: [logRow({ pages_read: 100 })],
    });
    renderApp('/books/42');
    expect(await screen.findByText('100 of 496 pages (20%)')).toBeInTheDocument();
    const user = userEvent.setup();
    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '24');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));
    expect(await screen.findByText('124 of 496 pages (25%)')).toBeInTheDocument();
  });

  it.each([
    ['', 'Enter a whole number of pages.'],
    ['0', 'Log at least 1 page.'],
    ['2.5', 'Enter a whole number of pages.'],
  ])('rejects %j pages without a request', async (value, message) => {
    const calls = setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    if (value) await user.type(within(logForm()).getByLabelText('Pages read (required)'), value);
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    const pages = within(logForm()).getByLabelText('Pages read (required)');
    expect(pages).toHaveAccessibleDescription(message);
    expect(pages).toHaveFocus(); // the error is next to the field, and focus moves there
    expect(within(logForm()).getByRole('button', { name: 'Log' })).toBeEnabled();
    expect(calls.posts).toHaveLength(0);
  });

  it('leaves a blank date out of the request, so the API logs today', async () => {
    const calls = setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    await user.clear(within(logForm()).getByLabelText('Date (optional)'));
    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '9');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    expect(await screen.findByText(/^Logged 9 pages for /)).toBeInTheDocument();
    expect(calls.posts).toEqual([{ book_id: 42, pages_read: 9 }]); // no log_date: null
  });

  it('shows the API daily limit on the pages field', async () => {
    setup({ entry: shelfEntry({ status: 'reading' }) });
    server.use(
      http.post(api('/logs/'), () =>
        HttpResponse.json(
          {
            pages_read: [
              'That would make 3000 pages in one day; the limit is 2000. Check for a typo.',
            ],
          },
          { status: 400 },
        ),
      ),
    );
    renderApp('/books/42');
    const user = userEvent.setup();
    await screen.findByRole('form', { name: 'Log pages' });
    await user.type(within(logForm()).getByLabelText('Pages read (required)'), '3000');
    await user.click(within(logForm()).getByRole('button', { name: 'Log' }));

    await waitFor(() =>
      expect(within(logForm()).getByLabelText('Pages read (required)')).toHaveAccessibleDescription(
        /limit is 2000/,
      ),
    );
  });
});

describe('the log list', () => {
  it('lists logs newest first, or says there are none', async () => {
    setup({
      entry: shelfEntry({ status: 'reading' }),
      logs: [
        logRow({ id: 1, log_date: '2026-11-01', pages_read: 10 }),
        logRow({ id: 2, log_date: '2026-11-05', pages_read: 1 }),
      ],
    });
    renderApp('/books/42');
    const items = await within(
      await screen.findByRole('list', { name: 'Reading log' }),
    ).findAllByRole('listitem');
    expect(items.map((li) => li.textContent)).toEqual([
      expect.stringContaining('Nov 5, 2026'),
      expect.stringContaining('Nov 1, 2026'),
    ]);
    expect(items[0]).toHaveTextContent('1 page'); // singular
  });

  it('shows an empty message', async () => {
    setup({ entry: shelfEntry({ status: 'reading' }) });
    renderApp('/books/42');
    expect(await screen.findByText('No pages logged for this book yet.')).toBeInTheDocument();
  });

  it('edits a log: PATCH sets the total and sends only what changed', async () => {
    const calls = setup({
      entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }),
      logs: [logRow({ id: 1, log_date: '2026-11-03', pages_read: 30 })],
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Edit the log for Nov 3, 2026' }));
    const form = screen.getByRole('form', { name: 'Edit the log for Nov 3, 2026' });
    const pages = within(form).getByLabelText('Pages read (required)');
    await user.clear(pages);
    await user.type(pages, '12');
    await user.click(within(form).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Saved Nov 3, 2026: 12 pages.')).toBeInTheDocument();
    expect(calls.patches).toEqual([{ id: '1', body: { pages_read: 12 } }]);
    expect(await within(logList()).findByText('12 pages')).toBeInTheDocument();
  });

  it('keeps the log day when the date is cleared while editing', async () => {
    const calls = setup({
      entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }),
      logs: [logRow({ id: 1, log_date: '2026-11-03', pages_read: 30 })],
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Edit the log for Nov 3, 2026' }));
    const form = screen.getByRole('form', { name: 'Edit the log for Nov 3, 2026' });
    const date = within(form).getByLabelText('Date (optional)');
    await user.clear(date);
    expect(date).toHaveAccessibleDescription('Left blank, this keeps Nov 3, 2026.');
    const pages = within(form).getByLabelText('Pages read (required)');
    await user.clear(pages);
    await user.type(pages, '31');
    await user.click(within(form).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Saved Nov 3, 2026: 31 pages.')).toBeInTheDocument();
    expect(calls.patches).toEqual([{ id: '1', body: { pages_read: 31 } }]);
  });

  it('cancelling an edit sends nothing', async () => {
    const calls = setup({ entry: shelfEntry({ status: 'reading' }), logs: [logRow()] });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Edit the log for Nov 3, 2026' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByText('30 pages')).toBeInTheDocument();
    expect(calls.patches).toHaveLength(0);
  });

  it('moving a log onto a taken day explains it and links to that day', async () => {
    setup({
      entry: shelfEntry({ status: 'reading', started_at: '2026-11-01' }),
      logs: [
        logRow({ id: 1, log_date: '2026-11-03', pages_read: 30 }),
        logRow({ id: 2, log_date: '2026-11-04', pages_read: 15 }),
      ],
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Edit the log for Nov 3, 2026' }));
    const form = screen.getByRole('form', { name: 'Edit the log for Nov 3, 2026' });
    const date = within(form).getByLabelText('Date (optional)');
    await user.clear(date);
    await user.type(date, '2026-11-04');
    await user.click(within(form).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(date).toHaveAccessibleDescription(/You already logged this book on 2026-11-04/),
    );
    await user.click(within(form).getByRole('button', { name: 'Go to Nov 4, 2026' }));
    expect(document.getElementById('log-row-2')).toHaveFocus();
  });

  it('deletes a log after confirming', async () => {
    const calls = setup({
      entry: shelfEntry({ status: 'reading' }),
      logs: [logRow({ id: 1, log_date: '2026-11-03', pages_read: 30 })],
    });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete the log for Nov 3, 2026' }));
    const dialog = screen.getByRole('dialog', { name: 'Delete the log for Nov 3, 2026?' });
    expect(dialog).toHaveTextContent('This removes 30 pages from your reading history.');
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText('Deleted the log for Nov 3, 2026.')).toBeInTheDocument();
    expect(calls.deletes).toEqual(['1']);
    expect(await screen.findByText('No pages logged for this book yet.')).toBeInTheDocument();
  });

  it('cancelling a delete sends nothing', async () => {
    const calls = setup({ entry: shelfEntry({ status: 'reading' }), logs: [logRow()] });
    renderApp('/books/42');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete the log for Nov 3, 2026' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Cancel' }));
    expect(calls.deletes).toHaveLength(0);
    expect(screen.getByText('30 pages')).toBeInTheDocument();
  });

  it('is not shown for a book that is not on the shelf', async () => {
    setRefreshToken('refresh-1');
    server.use(
      ...authHandlers(),
      http.get(api('/books/42/'), () => HttpResponse.json(bookDetail())),
      http.get(api('/shelf/'), () => HttpResponse.json(page([]))),
    );
    renderApp('/books/42');
    await screen.findByRole('heading', { name: 'Add to your shelf' });
    expect(screen.queryByRole('form', { name: 'Log pages' })).not.toBeInTheDocument();
  });
});
