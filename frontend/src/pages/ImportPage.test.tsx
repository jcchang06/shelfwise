import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { GoodreadsImport, ImportRow } from '../api/imports';
import { setRefreshToken } from '../api/tokens';
import type { SearchResult } from '../api/types';
import { BUSY_RETRY_MS } from '../hooks/useImports';
import { page } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

function anImport(overrides: Partial<GoodreadsImport> = {}): GoodreadsImport {
  return {
    id: 5,
    status: 'pending',
    total_rows: 10,
    processed_rows: 0,
    created_count: 0,
    updated_count: 0,
    skipped_count: 0,
    unmatched_count: 0,
    failed_count: 0,
    placeholder_dnf_count: 0,
    error: '',
    created_at: '2026-11-16T18:00:00Z',
    finished_at: null,
    ...overrides,
  };
}

function aRow(overrides: Partial<ImportRow> = {}): ImportRow {
  return {
    id: 71,
    row_number: 3,
    title: 'The Glass Orchard',
    author: 'Mara Vell',
    additional_authors: '',
    isbn_13: '',
    year_published: 2018,
    status: 'finished',
    rating: 4,
    date_read: '2024-03-09',
    state: 'unmatched',
    note: 'No book with this title and author found.',
    search_query: 'The Glass Orchard Mara Vell',
    ...overrides,
  };
}

const candidate = (overrides: Partial<SearchResult> = {}): SearchResult => ({
  source: 'google_books',
  source_id: 'vol9',
  title: 'The Glass Orchard',
  authors: ['Mara Vell'],
  description: '',
  genres: [],
  page_count: 412,
  published_date: '2018',
  isbn_13: '',
  cover_url: '',
  book_id: null,
  shelf: null,
  ...overrides,
});

interface Calls {
  process: number;
  uploads: { name: string }[];
  resolves: Record<string, unknown>[];
  dismisses: number[];
  searches: string[];
}

/**
 * Logged in; /api/imports/5/ starts as `start` and each process call returns the next
 * item of `steps` (an import or a status code). Rows are served from `unmatched`/`failed`.
 */
function setup({
  start = anImport(),
  steps = [] as (GoodreadsImport | number)[],
  unmatched = [] as ImportRow[],
  failed = [] as ImportRow[],
  results = [candidate()],
  past = [] as GoodreadsImport[],
} = {}): Calls {
  setRefreshToken('refresh-1');
  const calls: Calls = { process: 0, uploads: [], resolves: [], dismisses: [], searches: [] };
  let current = start;
  let rows = [...unmatched];
  server.use(
    ...authHandlers(),
    http.get(api('/imports/'), () => HttpResponse.json(page(past))),
    http.post(api('/imports/'), ({ request }) => {
      // Don't read the body: in jsdom a multipart body built from a File never finishes
      // streaming (real browsers are fine). The test checks the FormData contents instead.
      calls.uploads.push({ name: request.headers.get('Content-Type') ?? '' });
      current = anImport();
      return HttpResponse.json(current, { status: 201 });
    }),
    http.get(api('/imports/5/'), () => HttpResponse.json(current)),
    http.post(api('/imports/5/process/'), () => {
      calls.process += 1;
      const next = steps.shift();
      if (typeof next === 'number') {
        return HttpResponse.json(
          { detail: 'This import is already being processed.' },
          { status: next },
        );
      }
      if (next) current = next;
      return HttpResponse.json(current);
    }),
    http.get(api('/imports/5/rows/'), ({ request }) => {
      const state = new URL(request.url).searchParams.get('state');
      return HttpResponse.json(page(state === 'failed' ? failed : rows));
    }),
    http.post(api('/imports/5/rows/:row/resolve/'), async ({ request, params }) => {
      calls.resolves.push((await request.json()) as Record<string, unknown>);
      rows = rows.filter((r) => String(r.id) !== params.row);
      current = {
        ...current,
        unmatched_count: rows.length,
        created_count: current.created_count + 1,
      };
      return HttpResponse.json({
        row: { id: Number(params.row), state: 'created', note: '' },
        book_id: 42,
        user_book_id: 7,
        import: current,
      });
    }),
    http.post(api('/imports/5/rows/:row/dismiss/'), ({ params }) => {
      calls.dismisses.push(Number(params.row));
      rows = rows.filter((r) => String(r.id) !== params.row);
      current = {
        ...current,
        unmatched_count: rows.length,
        skipped_count: current.skipped_count + 1,
      };
      return HttpResponse.json({
        row: { id: Number(params.row), state: 'dismissed', note: 'Dismissed.' },
        book_id: null,
        user_book_id: null,
        import: current,
      });
    }),
    http.get(api('/books/search/'), ({ request }) => {
      calls.searches.push(new URL(request.url).searchParams.get('q') ?? '');
      return HttpResponse.json({ source: 'google_books', page: 1, next_page: null, results });
    }),
  );
  return calls;
}

describe('upload', () => {
  it('has an Import link in the navigation', async () => {
    setup();
    renderApp('/import');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Import' })).toHaveAttribute('href', '/import');
  });

  it('explains how to export and that the file is never stored', async () => {
    setup();
    renderApp('/import');
    expect(
      await screen.findByText(/My Books → Import and export → Export Library/),
    ).toBeInTheDocument();
    expect(screen.getByText(/never stored/)).toBeInTheDocument();
  });

  it.each([
    [null, 'Choose your Goodreads export (a .csv file).'],
    [
      new File(['x'], 'library.xlsx'),
      'That isn’t a .csv file. Goodreads exports a file ending in .csv.',
    ],
    [
      new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'big.csv'),
      'That file is too large. The limit is 5 MB.',
    ],
  ])('checks the file before uploading (%#)', async (file, message) => {
    const calls = setup();
    renderApp('/import');
    const user = userEvent.setup({ applyAccept: false });
    const input = await screen.findByLabelText('Goodreads export (CSV)');
    if (file) await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: 'Start import' }));
    expect(input).toHaveAccessibleDescription(message);
    expect(calls.uploads).toHaveLength(0);
  });

  it('uploads the file as multipart and opens the import', async () => {
    const calls = setup({
      steps: [
        anImport({
          status: 'done',
          processed_rows: 10,
          created_count: 10,
          finished_at: '2026-11-16T18:05:00Z',
        }),
      ],
    });
    const append = vi.spyOn(FormData.prototype, 'append');
    renderApp('/import');
    const user = userEvent.setup();
    const file = new File(['Book Id,Title\n'], 'goodreads_library_export.csv', {
      type: 'text/csv',
    });
    await user.upload(await screen.findByLabelText('Goodreads export (CSV)'), file);
    await user.click(screen.getByRole('button', { name: 'Start import' }));

    expect(await screen.findByRole('heading', { name: 'Goodreads import' })).toBeInTheDocument();
    expect(append).toHaveBeenCalledWith('file', file);
    expect(calls.uploads).toHaveLength(1);
    expect(calls.uploads[0].name).toMatch(/^multipart\/form-data; boundary=/);
    append.mockRestore();
  });

  it('shows the server’s file error', async () => {
    setup();
    server.use(
      http.post(api('/imports/'), () =>
        HttpResponse.json(
          { file: ["This doesn't look like a Goodreads export (missing columns: ISBN13)."] },
          { status: 400 },
        ),
      ),
    );
    renderApp('/import');
    const user = userEvent.setup();
    const input = await screen.findByLabelText('Goodreads export (CSV)');
    await user.upload(input, new File(['x'], 'other.csv', { type: 'text/csv' }));
    await user.click(screen.getByRole('button', { name: 'Start import' }));
    await waitFor(() => expect(input).toHaveAccessibleDescription(/missing columns: ISBN13/));
  });

  it('lists past imports', async () => {
    setup({ past: [anImport({ status: 'done', processed_rows: 10, unmatched_count: 2 })] });
    renderApp('/import');
    const link = await screen.findByRole('link', { name: 'Nov 16, 2026' });
    expect(link).toHaveAttribute('href', '/import/5');
    expect(link.closest('li')).toHaveTextContent('Finished · 10 of 10 rows · 2 need a match');
  });
});

describe('progress', () => {
  afterEach(() => vi.useRealTimers());

  it('runs batches until done, then shows the summary', async () => {
    const calls = setup({
      steps: [
        anImport({ status: 'running', processed_rows: 4 }),
        anImport({
          status: 'done',
          processed_rows: 10,
          created_count: 7,
          updated_count: 1,
          skipped_count: 1,
          unmatched_count: 1,
          finished_at: '2026-11-16T18:05:00Z',
        }),
      ],
    });
    renderApp('/import/5');

    expect(await screen.findByRole('heading', { name: 'Import finished' })).toBeInTheDocument();
    expect(calls.process).toBe(2);
    const tiles = screen.getByText('Added to your shelf').closest('dl') as HTMLElement;
    expect(within(tiles).getByText('7')).toBeInTheDocument();
    expect(screen.getByText(/10 rows from Goodreads, finished Nov 16, 2026/)).toBeInTheDocument();
  });

  it('shows the progress bar while running', async () => {
    setup({
      start: anImport({ status: 'running', processed_rows: 4 }),
      steps: [anImport({ status: 'paused', processed_rows: 4, error: 'Budget used up.' })],
    });
    renderApp('/import/5');
    const bar = await screen.findByRole('progressbar', { name: 'Import progress' });
    expect(bar).toHaveAttribute('value', '4');
    expect(bar).toHaveAttribute('max', '10');
    expect(screen.getByText('4 of 10 rows (40%)')).toBeInTheDocument();
  });

  it('waits and retries when another process holds the import (409)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = setup({
      steps: [
        409,
        anImport({ status: 'done', processed_rows: 10, finished_at: '2026-11-16T18:05:00Z' }),
      ],
    });
    renderApp('/import/5');
    expect(
      await screen.findByText(/Another process is working on this import/),
    ).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(BUSY_RETRY_MS));

    expect(await screen.findByRole('heading', { name: 'Import finished' })).toBeInTheDocument();
    expect(calls.process).toBe(2);
  });

  it('explains a pause and can try again', async () => {
    const calls = setup({
      steps: [
        anImport({
          status: 'paused',
          processed_rows: 6,
          error: "The import's Google budget (600 a day) is used up until midnight Pacific.",
        }),
        anImport({ status: 'done', processed_rows: 10, finished_at: '2026-11-16T18:05:00Z' }),
      ],
    });
    renderApp('/import/5');
    expect(await screen.findByRole('heading', { name: 'Import paused' })).toBeInTheDocument();
    expect(
      screen.getByText(/600 a day.*It will continue automatically tonight/),
    ).toBeInTheDocument();
    expect(calls.process).toBe(1); // stopped on the pause

    await userEvent.setup().click(screen.getByRole('button', { name: 'try again now' }));
    expect(await screen.findByRole('heading', { name: 'Import finished' })).toBeInTheDocument();
    expect(calls.process).toBe(2);
  });

  it('links to the DNF shelf when imported DNFs have no reason yet', async () => {
    setup({
      start: anImport({
        status: 'done',
        processed_rows: 10,
        placeholder_dnf_count: 3,
        finished_at: '2026-11-16T18:05:00Z',
      }),
    });
    renderApp('/import/5');
    expect(await screen.findByText(/3 imported DNFs have no reason yet/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Set reasons on your DNF shelf' })).toHaveAttribute(
      'href',
      '/shelf?status=dnf',
    );
  });

  it('shows an unknown import as not found', async () => {
    setup();
    server.use(
      http.get(api('/imports/5/'), () =>
        HttpResponse.json({ detail: 'Not found.' }, { status: 404 }),
      ),
    );
    renderApp('/import/5');
    expect(await screen.findByRole('heading', { name: 'Import not found' })).toBeInTheDocument();
  });
});

describe('unmatched and failed rows', () => {
  const done = anImport({
    status: 'done',
    processed_rows: 10,
    unmatched_count: 1,
    finished_at: '2026-11-16T18:05:00Z',
  });

  it('lists them with why they didn’t match', async () => {
    setup({ start: done, unmatched: [aRow()] });
    renderApp('/import/5');
    expect(
      await screen.findByRole('heading', { name: 'Books that need a match (1)' }),
    ).toBeInTheDocument();
    expect(screen.getByText('No book with this title and author found.')).toBeInTheDocument();
    expect(screen.getByText('Finished · 4★ · read Mar 9, 2024')).toBeInTheDocument();
  });

  it('searches with the pre-filled query and resolves with the picked book', async () => {
    const calls = setup({ start: done, unmatched: [aRow()] });
    renderApp('/import/5');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Find a match' }));

    expect(screen.getByRole('searchbox', { name: 'Search for The Glass Orchard' })).toHaveValue(
      'The Glass Orchard Mara Vell',
    );
    expect(await screen.findByRole('img', { name: 'Powered by Google' })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /View The Glass Orchard on Google Books/ }),
    ).toBeInTheDocument();
    expect(calls.searches).toEqual(['The Glass Orchard Mara Vell']);

    await user.click(
      screen.getByRole('button', { name: 'Use The Glass Orchard for The Glass Orchard' }),
    );

    expect(
      await screen.findByText('The Glass Orchard: matched and added to your shelf.'),
    ).toBeInTheDocument();
    expect(calls.resolves).toEqual([{ source: 'google_books', source_id: 'vol9' }]);
    await waitFor(() =>
      expect(
        screen.queryByRole('heading', { name: /Books that need a match/ }),
      ).not.toBeInTheDocument(),
    );
  });

  it('resolves with book_id when the result is already in the catalog', async () => {
    const calls = setup({
      start: done,
      unmatched: [aRow()],
      results: [candidate({ book_id: 42 })],
    });
    renderApp('/import/5');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Find a match' }));
    await user.click(await screen.findByRole('button', { name: /^Use The Glass Orchard/ }));
    await screen.findByText(/matched and added to your shelf/);
    expect(calls.resolves).toEqual([{ book_id: 42 }]);
  });

  it('dismisses a row', async () => {
    const calls = setup({ start: done, unmatched: [aRow()] });
    renderApp('/import/5');
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Dismiss The Glass Orchard' }));
    expect(await screen.findByText('Dismissed The Glass Orchard.')).toBeInTheDocument();
    expect(calls.dismisses).toEqual([71]);
  });

  it('lists rows that couldn’t be imported, with reasons', async () => {
    setup({
      start: done,
      failed: [
        aRow({
          id: 80,
          row_number: 11,
          title: '(untitled)',
          state: 'failed',
          note: 'This row has no Goodreads Book Id or title.',
        }),
      ],
    });
    renderApp('/import/5');
    expect(await screen.findByText("1 row couldn't be imported")).toBeInTheDocument();
    expect(screen.getByText(/This row has no Goodreads Book Id or title\./)).toBeInTheDocument();
  });
});
