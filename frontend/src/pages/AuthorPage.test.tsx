import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import type { AuthorDetail, AuthorWork } from '../api/authors';
import { setRefreshToken } from '../api/tokens';
import { page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

function work(overrides: Partial<AuthorWork> = {}): AuthorWork {
  return {
    title: 'Winter Ledger',
    work_key: 'OL8W',
    first_publish_year: 2026,
    cover_url: '',
    book_id: null,
    series_name: null,
    series_number: null,
    shelf: null,
    ...overrides,
  };
}

function author(overrides: Partial<AuthorDetail> = {}): AuthorDetail {
  return {
    id: 9,
    name: 'Mara Vell',
    open_library_key: 'OL9A',
    open_library_url: 'https://openlibrary.org/authors/OL9A',
    works_unavailable: false,
    groups: [
      {
        series_name: 'Glass',
        works: [
          work({
            title: 'The Glass Orchard',
            work_key: 'OL3W',
            first_publish_year: 2019,
            book_id: 42,
            series_name: 'Glass',
            series_number: '1.0',
            shelf: { id: 7, status: 'finished' },
          }),
          work({
            title: 'Glass Houses',
            work_key: 'OL4W',
            first_publish_year: 2021,
            series_name: 'Glass',
            series_number: '2.0',
          }),
        ],
      },
      { series_name: null, works: [work()] },
    ],
    ...overrides,
  };
}

/** Logged in; GET /api/authors/9/ answers `detail` (or a Response); POSTs are recorded. */
function setup(detail: AuthorDetail | Response = author()) {
  setRefreshToken('refresh-1');
  const posts: unknown[] = [];
  let current = detail;
  server.use(
    ...authHandlers(),
    http.get(api('/authors/9/'), () =>
      current instanceof Response ? current : HttpResponse.json(current),
    ),
    http.get(api('/shelf/'), () => HttpResponse.json(page([]))),
    http.post(api('/shelf/'), async ({ request }) => {
      posts.push(await request.json());
      // After the add, the author page shows the book on the shelf.
      if (!(current instanceof Response)) {
        current = {
          ...current,
          groups: current.groups.map((group) => ({
            ...group,
            works: group.works.map((w) =>
              w.work_key === 'OL8W'
                ? { ...w, book_id: 50, shelf: { id: 70, status: 'want_to_read' } }
                : w,
            ),
          })),
        };
      }
      return HttpResponse.json(shelfEntry({ id: 70 }), { status: 201 });
    }),
  );
  return posts;
}

describe('author page', () => {
  it('lists the books by series, then the rest, with shelf status and links', async () => {
    setup();
    renderApp('/authors/9');

    expect(await screen.findByRole('heading', { level: 1, name: 'Mara Vell' })).toBeInTheDocument();
    expect(
      screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent),
    ).toEqual(['Glass series', 'Other books']);

    const glass = screen.getByRole('region', { name: 'Glass series' });
    const titles = within(glass).getAllByRole('heading', { level: 3 });
    expect(titles.map((t) => t.textContent)).toEqual(['The Glass Orchard', 'Glass Houses']);
    expect(within(glass).getByText('Glass #1 · 2019')).toBeInTheDocument();
    expect(within(glass).getByRole('link', { name: 'The Glass Orchard' })).toHaveAttribute(
      'href',
      '/books/42',
    );
    expect(
      within(glass).getByRole('link', { name: 'On your shelf · Finished' }),
    ).toBeInTheDocument();

    const link = screen.getByRole('link', { name: /Mara Vell on Open Library/ });
    expect(link).toHaveAttribute('href', 'https://openlibrary.org/authors/OL9A');
    expect(screen.getByText(/3 books, from Open Library and your catalog/)).toBeInTheDocument();
  });

  it('adds a book from Open Library to the shelf, then shows it there', async () => {
    const posts = setup();
    renderApp('/authors/9');
    const other = await screen.findByRole('region', { name: 'Other books' });
    const user = userEvent.setup();
    await user.click(within(other).getByRole('button', { name: 'Add' }));

    expect(
      await within(other).findByRole('link', { name: 'On your shelf · Want to read' }),
    ).toBeInTheDocument();
    expect(posts).toEqual([{ source: 'open_library', source_id: 'OL8W', status: 'want_to_read' }]);
    expect(screen.getByText('Added Winter Ledger to Want to read.')).toBeInTheDocument();
  });

  it('adds a catalog book by book_id', async () => {
    const posts = setup(
      author({
        groups: [
          {
            series_name: null,
            works: [work({ book_id: 51, work_key: null, title: 'Salt Roads' })],
          },
        ],
      }),
    );
    renderApp('/authors/9');
    expect(await screen.findByRole('heading', { level: 2, name: 'Books' })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Add' }));
    await screen.findByText('Added Salt Roads to Want to read.');
    expect(posts).toEqual([{ book_id: 51, status: 'want_to_read' }]);
  });

  it('says when Open Library could not be reached', async () => {
    setup(author({ works_unavailable: true, open_library_url: null }));
    renderApp('/authors/9');
    expect(await screen.findByText(/Couldn't reach Open Library/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /on Open Library/ })).not.toBeInTheDocument();
  });

  it('says when the author could not be matched on Open Library', async () => {
    setup(author({ open_library_key: null, open_library_url: null }));
    renderApp('/authors/9');
    expect(await screen.findByText(/match this author on Open Library/)).toBeInTheDocument();
  });

  it('shows not found for an unknown author', async () => {
    setup(HttpResponse.json({ detail: 'No author with this ID.' }, { status: 404 }));
    renderApp('/authors/9');
    expect(await screen.findByRole('heading', { name: 'Author not found' })).toBeInTheDocument();
  });

  it('shows not found for a non-numeric id without a request', async () => {
    setup();
    renderApp('/authors/abc');
    expect(await screen.findByRole('heading', { name: 'Author not found' })).toBeInTheDocument();
  });
});
