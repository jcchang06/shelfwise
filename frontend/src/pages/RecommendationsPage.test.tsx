import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type { RecommendationsResponse, SuggestedBook } from '../api/recommendations';
import { setRefreshToken } from '../api/tokens';
import { bookDetail, page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

function suggested(
  id: number,
  title: string,
  overrides: Partial<SuggestedBook> = {},
): SuggestedBook {
  return {
    id,
    title,
    author_links: [{ id: 9, name: 'Mara Vell' }],
    cover_url: '',
    page_count: 320,
    published_date: '2019',
    shelf: null,
    ...overrides,
  };
}

function picks(
  results: SuggestedBook[],
  computedAt: string | null = '2026-11-18T10:05:00Z',
): RecommendationsResponse {
  return {
    computed_at: computedAt,
    results: results.map((book, i) => ({ rank: i + 1, book, because_of: null })),
  };
}

function setup(body: RecommendationsResponse) {
  setRefreshToken('refresh-1');
  const posts: unknown[] = [];
  let current = body;
  server.use(
    ...authHandlers(),
    http.get(api('/recommendations/'), () => HttpResponse.json(current)),
    http.post(api('/shelf/'), async ({ request }) => {
      const sent = (await request.json()) as { book_id: number };
      posts.push(sent);
      current = {
        ...current,
        results: current.results.map((p) =>
          p.book.id === sent.book_id
            ? { ...p, book: { ...p.book, shelf: { id: 70, status: 'want_to_read' } } }
            : p,
        ),
      };
      return HttpResponse.json(shelfEntry({ id: 70 }), { status: 201 });
    }),
  );
  return posts;
}

describe('For you page', () => {
  it('lists the picks in order with authors, year and the add form', async () => {
    setup(
      picks([
        suggested(1, 'Salt Roads'),
        suggested(2, 'Winter Ledger', { shelf: { id: 5, status: 'reading' } }),
      ]),
    );
    renderApp('/for-you');
    expect(await screen.findByRole('heading', { level: 1, name: 'For you' })).toBeInTheDocument();
    const headings = await screen.findAllByRole('heading', { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual(['Salt Roads', 'Winter Ledger']);
    const items = headings.map((h) => h.closest('li') as HTMLElement);
    expect(within(items[0]).getByRole('link', { name: 'Mara Vell' })).toHaveAttribute(
      'href',
      '/authors/9',
    );
    expect(within(items[0]).getByText(/2019/)).toBeInTheDocument();
    expect(within(items[0]).getByRole('button', { name: 'Add' })).toBeInTheDocument();
    expect(within(items[1]).getByRole('link', { name: 'On your shelf · Reading' })).toHaveAttribute(
      'href',
      '/books/2',
    );
    expect(screen.getByText(/last updated/)).toBeInTheDocument();
  });

  it('adds a pick by book_id and then shows it on the shelf', async () => {
    const posts = setup(picks([suggested(1, 'Salt Roads')]));
    renderApp('/for-you');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Add' }));
    expect(
      await screen.findByRole('link', { name: 'On your shelf · Want to read' }),
    ).toBeInTheDocument();
    expect(posts).toEqual([{ book_id: 1, status: 'want_to_read' }]);
    expect(screen.getByText('Added Salt Roads to Want to read.')).toBeInTheDocument();
  });

  it('explains when there is no run yet', async () => {
    setup(picks([], null));
    renderApp('/for-you');
    expect(await screen.findByText(/after the first nightly update/)).toBeInTheDocument();
  });

  it('asks for ratings when a run found nothing for the reader', async () => {
    setup(picks([]));
    renderApp('/for-you');
    expect(await screen.findByText(/Rate a few finished books 4★ or higher/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Your finished books' })).toHaveAttribute(
      'href',
      '/shelf?status=finished',
    );
  });

  it('is in the main navigation', async () => {
    setup(picks([]));
    renderApp('/for-you');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'For you' })).toHaveAttribute('href', '/for-you');
  });
});

describe('More like this on the book page', () => {
  function setupBook(similar: SuggestedBook[] | Response) {
    setRefreshToken('refresh-1');
    server.use(
      ...authHandlers(),
      http.get(api('/books/42/'), () => HttpResponse.json(bookDetail())),
      http.get(api('/shelf/'), () => HttpResponse.json(page([]))),
      http.get(api('/books/42/similar/'), () =>
        similar instanceof Response ? similar : HttpResponse.json({ results: similar }),
      ),
    );
  }

  it('shows similar books with links and shelf status', async () => {
    setupBook([
      suggested(7, 'Artemis', { shelf: { id: 3, status: 'finished' } }),
      suggested(8, 'The Martian'),
    ]);
    renderApp('/books/42');
    const section = await screen.findByRole('region', { name: 'More like this' });
    expect(
      within(section)
        .getAllByRole('heading', { level: 3 })
        .map((h) => h.textContent),
    ).toEqual(['Artemis', 'The Martian']);
    expect(
      within(section).getByRole('link', { name: 'On your shelf · Finished' }),
    ).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Add' })).toBeInTheDocument();
  });

  it('is hidden when there are none, or the endpoint fails', async () => {
    setupBook([]);
    renderApp('/books/42');
    await screen.findByRole('heading', { level: 1, name: 'Project Hail Mary' });
    expect(screen.queryByRole('region', { name: 'More like this' })).not.toBeInTheDocument();
  });

  it('is hidden when an older API has no such endpoint', async () => {
    setupBook(HttpResponse.json({ detail: 'Not found.' }, { status: 404 }));
    renderApp('/books/42');
    await screen.findByRole('heading', { level: 1, name: 'Project Hail Mary' });
    expect(screen.queryByRole('region', { name: 'More like this' })).not.toBeInTheDocument();
  });
});
