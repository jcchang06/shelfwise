import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import type { ReadingLog } from '../api/logs';
import type { Stats } from '../api/stats';
import { setRefreshToken } from '../api/tokens';
import type { ShelfEntry } from '../api/types';
import { localDateISO } from '../dates';
import { page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, EMPTY_STATS, server } from '../test/server';

// jsdom can't draw on a canvas: replace Chart.js's <Bar> with a stub that exposes the
// labels and datasets it was given, so tests check the data rather than pixels.
vi.mock('react-chartjs-2', () => ({
  Bar: ({
    data,
  }: {
    data: { labels: string[]; datasets: { label: string; data: number[] }[] };
  }) => (
    <pre data-testid="bar-chart">
      {JSON.stringify({
        labels: data.labels,
        datasets: data.datasets.map((d) => ({ label: d.label, data: d.data })),
      })}
    </pre>
  ),
}));

const YEAR = new Date().getFullYear();

function stats(overrides: Partial<Stats> = {}): Stats {
  return { ...EMPTY_STATS, year: YEAR, ...overrides } as Stats;
}

const reading = (id: number, title: string, overrides: Partial<ShelfEntry> = {}) =>
  shelfEntry({
    id,
    status: 'reading',
    book: { id: 40 + id, title, authors: ['A. Author'], cover_url: '', page_count: 400 },
    ...overrides,
  });

interface Calls {
  posts: Record<string, unknown>[];
  statsYears: string[];
}

/** Logged in; reading shelf, today's logs and stats answered from in-memory state. */
function setup({
  entries = [] as ShelfEntry[],
  today = [] as ReadingLog[],
  statsFor = ((): Stats => stats()) as (year: string) => Stats,
} = {}): Calls {
  setRefreshToken('refresh-1');
  const calls: Calls = { posts: [], statsYears: [] };
  const logs = [...today];
  let current = [...entries];
  server.use(
    ...authHandlers(),
    http.get(api('/shelf/'), () => HttpResponse.json(page(current))),
    http.get(api('/logs/'), ({ request }) => {
      const url = new URL(request.url);
      const day = url.searchParams.get('from');
      return HttpResponse.json(page(logs.filter((l) => !day || l.log_date === day)));
    }),
    http.get(api('/stats/'), ({ request }) => {
      const year = new URL(request.url).searchParams.get('year') ?? '';
      calls.statsYears.push(year);
      return HttpResponse.json(statsFor(year));
    }),
    http.post(api('/logs/'), async ({ request }) => {
      const body = (await request.json()) as {
        book_id: number;
        pages_read: number;
        log_date: string;
      };
      calls.posts.push(body);
      let row = logs.find((l) => l.book_id === body.book_id && l.log_date === body.log_date);
      if (row) row.pages_read += body.pages_read;
      else {
        row = {
          id: logs.length + 1,
          book_id: body.book_id,
          log_date: body.log_date,
          pages_read: body.pages_read,
          created_at: '',
          updated_at: '',
        };
        logs.push(row);
      }
      current = current.map((e) =>
        e.book.id === body.book_id ? { ...e, pages_logged: e.pages_logged + body.pages_read } : e,
      );
      const entry = current.find((e) => e.book.id === body.book_id);
      return HttpResponse.json(
        {
          ...row,
          shelf_entry: entry
            ? {
                id: entry.id,
                status: entry.status,
                started_at: entry.started_at,
                pages_logged: entry.pages_logged,
              }
            : null,
        },
        { status: 201 },
      );
    }),
  );
  return calls;
}

const card = (title: string) =>
  screen.getByRole('link', { name: title }).closest('li') as HTMLElement;

describe('quick log', () => {
  it('comes first on the page, with a card per book being read', async () => {
    setup({ entries: [reading(1, 'Dune'), reading(2, 'Piranesi')] });
    renderApp('/dashboard');
    await screen.findByRole('link', { name: 'Dune' });

    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(headings[0]).toBe("Log today's pages");
    expect(headings[1]).toBe(`Your reading in ${YEAR}`);
    expect(screen.getByRole('link', { name: 'Piranesi' })).toHaveAttribute('href', '/books/42');
  });

  it("shows what's already logged today", async () => {
    setup({
      entries: [reading(1, 'Dune'), reading(2, 'Piranesi')],
      today: [
        {
          id: 1,
          book_id: 41,
          log_date: localDateISO(),
          pages_read: 30,
          created_at: '',
          updated_at: '',
        },
      ],
    });
    renderApp('/dashboard');
    expect(
      await within(await waitFor(() => card('Dune'))).findByText('Today: 30 pages'),
    ).toBeInTheDocument();
    expect(within(card('Piranesi')).getByText('Nothing logged today')).toBeInTheDocument();
  });

  it('logs today with Enter, clears the input, and updates the card', async () => {
    const calls = setup({ entries: [reading(1, 'Dune', { pages_logged: 100 })] });
    renderApp('/dashboard');
    const input = await screen.findByLabelText('Pages read today for Dune (required)');
    expect(input).toHaveAttribute('inputmode', 'numeric'); // number pad on phones

    await userEvent.setup().type(input, '25{Enter}');

    expect(await screen.findByText('Logged 25 pages for Dune today.')).toBeInTheDocument();
    expect(calls.posts).toEqual([{ book_id: 41, pages_read: 25, log_date: localDateISO() }]);
    expect(input).toHaveValue(null); // cleared after a successful log
    expect(await within(card('Dune')).findByText('Today: 25 pages')).toBeInTheDocument();
    expect(await within(card('Dune')).findByText('125 of 400 pages (31%)')).toBeInTheDocument();
  });

  it('adds to today when logging the same book again', async () => {
    setup({ entries: [reading(1, 'Dune')] });
    renderApp('/dashboard');
    const user = userEvent.setup();
    const input = await screen.findByLabelText('Pages read today for Dune (required)');
    await user.type(input, '10{Enter}');
    await within(card('Dune')).findByText('Today: 10 pages');
    await user.type(input, '5{Enter}');
    expect(await within(card('Dune')).findByText('Today: 15 pages')).toBeInTheDocument();
  });

  it('rejects invalid pages without a request and keeps what was typed', async () => {
    const calls = setup({ entries: [reading(1, 'Dune')] });
    renderApp('/dashboard');
    const input = await screen.findByLabelText('Pages read today for Dune (required)');
    await userEvent.setup().type(input, '0{Enter}');
    expect(input).toHaveAccessibleDescription('Log at least 1 page.');
    expect(input).toHaveFocus();
    expect(input).toHaveValue(0);
    expect(calls.posts).toHaveLength(0);
  });

  it('shows an API error on the card and keeps the input', async () => {
    setup({ entries: [reading(1, 'Dune')] });
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
    renderApp('/dashboard');
    const input = await screen.findByLabelText('Pages read today for Dune (required)');
    await userEvent.setup().type(input, '3000{Enter}');
    await waitFor(() => expect(input).toHaveAccessibleDescription(/limit is 2000/));
    expect(input).toHaveValue(3000);
  });

  it('points to the want-to-read list and search when nothing is being read', async () => {
    setup();
    renderApp('/dashboard');
    expect(await screen.findByText(/not reading anything right now/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'want-to-read list' })).toHaveAttribute(
      'href',
      '/shelf?status=want_to_read',
    );
    expect(screen.getByRole('link', { name: 'find a book' })).toHaveAttribute('href', '/search');
  });
});

describe('stats', () => {
  const full = (): Stats =>
    stats({
      totals: { pages: 2020, finished: 21, dnf: 4, average_rating: 3.9 },
      pages_per_month: EMPTY_STATS.pages_per_month.map((m, i) =>
        i === 2 ? { ...m, pages: 1020, dnf_pages: 40 } : i === 0 ? { ...m, pages: 1000 } : m,
      ),
      books_per_year: [
        { year: YEAR - 1, finished: 18, dnf: 3 },
        { year: YEAR, finished: 21, dnf: 4 },
        { year: null, finished: 2, dnf: 0 },
      ],
      genre_mix: [
        { genre: 'Science Fiction', finished: 7, dnf: 1 },
        { genre: 'Romance', finished: 1, dnf: 2 },
      ],
      rating_distribution: [
        { stars: 1, books: 0 },
        { stars: 2, books: 1 },
        { stars: 3, books: 2 },
        { stars: 4, books: 5 },
        { stars: 5, books: 4 },
      ],
    });

  const chartData = (title: string) => {
    const figure = screen.getByRole('heading', { name: title }).closest('figure') as HTMLElement;
    return JSON.parse(within(figure).getByTestId('bar-chart').textContent ?? '{}') as {
      labels: string[];
      datasets: { label: string; data: number[] }[];
    };
  };

  it('shows the totals', async () => {
    setup({ statsFor: full });
    renderApp('/dashboard');
    const totals = await screen.findByText('Pages read');
    const tiles = totals.closest('dl') as HTMLElement;
    expect(within(tiles).getByText('2,020')).toBeInTheDocument();
    expect(within(tiles).getByText('21')).toBeInTheDocument();
    expect(within(tiles).getByText('4')).toBeInTheDocument();
    expect(within(tiles).getByText('3.9')).toBeInTheDocument();
  });

  it('shows a dash for the average when nothing is rated', async () => {
    setup();
    renderApp('/dashboard');
    const tile = (await screen.findByText('Average rating')).closest('div') as HTMLElement;
    expect(within(tile).getByText('—')).toBeInTheDocument();
  });

  it('draws the four charts from the stats, with summaries and tables', async () => {
    setup({ statsFor: full });
    renderApp('/dashboard');
    await screen.findByRole('heading', { name: 'Pages per month' });

    const pages = chartData('Pages per month');
    expect(pages.labels[0]).toBe('Jan');
    expect(pages.datasets.map((d) => d.label)).toEqual(['Read', 'Did not finish']);
    expect(pages.datasets[0].data[2]).toBe(980); // 1,020 pages, 40 of them DNF
    expect(pages.datasets[1].data[2]).toBe(40);

    const perYear = chartData('Books per year');
    expect(perYear.labels).toEqual([String(YEAR - 1), String(YEAR), 'Date unknown']);
    expect(perYear.datasets[0].data).toEqual([18, 21, 2]);

    const genres = chartData('Genre mix');
    expect(genres.labels).toEqual(['Science Fiction', 'Romance']);
    expect(genres.datasets[1].data).toEqual([1, 2]);

    const ratings = chartData('Ratings (average 3.9)');
    expect(ratings.labels).toEqual(['1★', '2★', '3★', '4★', '5★']);
    expect(ratings.datasets).toHaveLength(1);

    // Text alternatives: the summary captions the figure and labels the chart.
    const summary = `2,020 pages in ${YEAR}, most in March (1,020). 40 were from books you didn't finish.`;
    expect(screen.getByText(summary)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: summary })).toBeInTheDocument();
    expect(screen.getAllByText('Show the numbers')).toHaveLength(4);
    expect(screen.getByRole('rowheader', { name: 'Date unknown' })).toBeInTheDocument();
  });

  it('shows empty messages instead of empty charts', async () => {
    setup();
    renderApp('/dashboard');
    expect(await screen.findByText(`No pages logged in ${YEAR} yet.`)).toBeInTheDocument();
    expect(screen.getByText('No finished or DNF books yet.')).toBeInTheDocument();
    expect(
      screen.getByText(`No genres for books finished or stopped in ${YEAR}.`),
    ).toBeInTheDocument();
    expect(screen.getByText(`No books rated in ${YEAR} yet.`)).toBeInTheDocument();
    expect(screen.queryByTestId('bar-chart')).not.toBeInTheDocument();
  });

  it('switches years through the URL', async () => {
    const calls = setup({ statsFor: full });
    renderApp('/dashboard');
    const picker = await screen.findByRole('combobox', { name: 'Year' });
    await waitFor(() =>
      expect(
        within(picker)
          .getAllByRole('option')
          .map((o) => o.textContent),
      ).toEqual([String(YEAR), String(YEAR - 1)]),
    );

    await userEvent.setup().selectOptions(picker, String(YEAR - 1));

    expect(
      await screen.findByRole('heading', { name: `Your reading in ${YEAR - 1}` }),
    ).toBeInTheDocument();
    await waitFor(() => expect(calls.statsYears).toContain(String(YEAR - 1)));
  });

  it('opens on the year in the URL', async () => {
    const calls = setup({ statsFor: full });
    renderApp(`/dashboard?year=${YEAR - 1}`);
    expect(
      await screen.findByRole('heading', { name: `Your reading in ${YEAR - 1}` }),
    ).toBeInTheDocument();
    expect(calls.statsYears[0]).toBe(String(YEAR - 1));
  });
});
