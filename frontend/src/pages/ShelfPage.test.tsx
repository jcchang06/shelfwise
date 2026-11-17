import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { setRefreshToken } from '../api/tokens';
import type { ShelfEntry } from '../api/types';
import { page, shelfEntry } from '../test/fixtures';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

/** Logged in; GET /api/shelf/ answered by `respond`. Returns the requested URLs. */
function setup(respond: (url: URL) => ShelfEntry[] | Response) {
  setRefreshToken('refresh-1');
  const requests: URL[] = [];
  server.use(
    ...authHandlers(),
    http.get(api('/shelf/'), ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      const result = respond(url);
      if (result instanceof Response) return result;
      const author = url.searchParams.get('author');
      return HttpResponse.json({
        ...page(result),
        filters: { author: author ? { id: Number(author), name: 'Mara Vell' } : null },
      });
    }),
  );
  return requests;
}

/** A shelf list page as the API returns it (with `filters`). */
const shelfPage = (...args: Parameters<typeof page<ShelfEntry>>) => ({
  ...page(...args),
  filters: { author: null },
});

const row = (title: string) =>
  screen.getByRole('link', { name: title }).closest('li') as HTMLElement;

describe('shelf page', () => {
  it('opens on Reading, sorted by recently updated, with links to each book', async () => {
    const requests = setup(() => [shelfEntry({ status: 'reading' })]);
    renderApp('/shelf');

    expect(await screen.findByRole('link', { name: 'Project Hail Mary' })).toHaveAttribute(
      'href',
      '/books/42',
    );
    expect(requests[0].searchParams.get('status')).toBe('reading');
    expect(requests[0].searchParams.get('ordering')).toBe('-updated_at');
    const shelves = screen.getByRole('navigation', { name: 'Shelves' });
    expect(within(shelves).getByRole('link', { name: 'Reading' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Andy Weir' })).toHaveAttribute('href', '/authors/1');
  });

  it('shows reading progress', async () => {
    setup(() => [shelfEntry({ status: 'reading', pages_logged: 120 })]);
    renderApp('/shelf');
    expect(await screen.findByText('120 of 496 pages (24%)')).toBeInTheDocument();
    const bar = screen.getByRole('progressbar', { name: 'Reading progress' });
    expect(bar).toHaveAttribute('value', '120');
    expect(bar).toHaveAttribute('max', '496');
  });

  it('caps the bar at 100% when more pages are logged than the book has', async () => {
    setup(() => [shelfEntry({ status: 'reading', pages_logged: 512 })]);
    renderApp('/shelf');
    expect(await screen.findByText('512 of 496 pages (100%)')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '496');
  });

  it('shows pages logged when the page count is unknown', async () => {
    setup(() => [
      shelfEntry({
        status: 'reading',
        pages_logged: 120,
        book: { ...shelfEntry().book, page_count: null },
      }),
    ]);
    renderApp('/shelf');
    expect(await screen.findByText('120 pages logged')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it.each([
    [
      'finished',
      shelfEntry({ status: 'finished', finished_at: '2025-03-09', rating: 4 }),
      /Finished Mar 9, 2025/,
    ],
    [
      'dnf',
      shelfEntry({ status: 'dnf', dnf_page: 120, dnf_reason: 'pacing' }),
      /Stopped at page 120 · Pacing/,
    ],
    ['want_to_read', shelfEntry({ status: 'want_to_read' }), /Added Nov 16, 2026/],
  ])('shows the %s line', async (status, entry, line) => {
    setup(() => [entry]);
    renderApp(`/shelf?status=${status}`);
    await screen.findByRole('link', { name: 'Project Hail Mary' });
    expect(within(row('Project Hail Mary')).getByText(line)).toBeInTheDocument();
    if (status === 'finished') {
      expect(screen.getByRole('img', { name: '4 out of 5 stars' })).toHaveTextContent('★★★★☆');
    }
  });

  it('switches shelves and sort order through the URL', async () => {
    const requests = setup(() => [shelfEntry({ status: 'finished' })]);
    renderApp('/shelf');
    await screen.findByRole('link', { name: 'Project Hail Mary' });
    const user = userEvent.setup();

    await user.click(
      within(screen.getByRole('navigation', { name: 'Shelves' })).getByRole('link', {
        name: 'Finished',
      }),
    );
    await user.selectOptions(screen.getByRole('combobox', { name: 'Sort by' }), 'title');
    await screen.findByRole('link', { name: 'Project Hail Mary' });

    const last = requests[requests.length - 1];
    expect(last.searchParams.get('status')).toBe('finished');
    expect(last.searchParams.get('ordering')).toBe('title');
    expect(
      within(screen.getByRole('navigation', { name: 'Shelves' })).getByRole('link', {
        name: 'Finished',
      }),
    ).toHaveAttribute('aria-current', 'page');
  });

  it('shows an empty state with a link to search', async () => {
    setup(() => []);
    renderApp('/shelf?status=dnf');
    expect(await screen.findByText(/No books marked DNF/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Find a book' })).toHaveAttribute('href', '/search');
  });

  it('loads more', async () => {
    const requests = setup((url) =>
      url.searchParams.get('page') === '2'
        ? HttpResponse.json(
            shelfPage([
              shelfEntry({
                id: 8,
                status: 'reading',
                book: { ...shelfEntry().book, id: 43, title: 'Artemis' },
              }),
            ]),
          )
        : HttpResponse.json(
            shelfPage([shelfEntry({ status: 'reading' })], 'http://x/api/shelf/?page=2'),
          ),
    );
    renderApp('/shelf');
    await screen.findByRole('link', { name: 'Project Hail Mary' });

    await userEvent.setup().click(screen.getByRole('button', { name: 'Load more' }));

    expect(await screen.findByRole('link', { name: 'Artemis' })).toBeInTheDocument();
    expect(requests.map((u) => u.searchParams.get('page'))).toEqual(['1', '2']);
  });

  it('has a Shelf link in the main navigation', async () => {
    setup(() => []);
    renderApp('/shelf');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Shelf' })).toHaveAttribute('href', '/shelf');
  });
});

describe('shelf bar', () => {
  const bar = () => screen.getByRole('navigation', { name: 'Shelves' });

  it('is on other pages too, one click from any shelf, with none marked current', async () => {
    const requests = setup(() => [shelfEntry({ status: 'dnf', dnf_reason: 'pacing' })]);
    renderApp('/search');
    await screen.findByRole('navigation', { name: 'Main' });
    const links = within(bar()).getAllByRole('link');
    expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Reading', '/shelf?status=reading'],
      ['Want to read', '/shelf?status=want_to_read'],
      ['Finished', '/shelf?status=finished'],
      ['DNF', '/shelf?status=dnf'],
    ]);
    expect(links.some((link) => link.hasAttribute('aria-current'))).toBe(false);

    await userEvent.setup().click(within(bar()).getByRole('link', { name: 'DNF' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Your shelf: Did not finish' }),
    ).toBeInTheDocument();
    expect(requests[requests.length - 1].searchParams.get('status')).toBe('dnf');
  });

  it('marks the current shelf and keeps the sort order when switching', async () => {
    setup(() => []);
    renderApp('/shelf?status=finished&sort=title');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Your shelf: Finished' }),
    ).toBeInTheDocument();
    expect(within(bar()).getByRole('link', { name: 'Finished' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(within(bar()).getByRole('link', { name: 'Reading' })).toHaveAttribute(
      'href',
      '/shelf?status=reading&sort=title',
    );
  });

  it('comes right after the main navigation in keyboard order', async () => {
    setup(() => []);
    renderApp('/search');
    const main = await screen.findByRole('navigation', { name: 'Main' });
    const user = userEvent.setup();
    within(main).getByRole('link', { name: 'Import' }).focus();
    await user.tab(); // past "Log out"
    await user.tab();
    expect(within(bar()).getByRole('link', { name: 'Reading' })).toHaveFocus();
  });
});

describe('filters and new sorts', () => {
  it('filters by rating through the URL, keeping the shelf and sort', async () => {
    const requests = setup(() => [shelfEntry({ status: 'finished', rating: 5 })]);
    renderApp('/shelf?status=finished&sort=title');
    await screen.findByRole('link', { name: 'Project Hail Mary' });
    await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Rating' }), '4');

    const last = await waitForRequest(requests, (u) => u.searchParams.get('rating') === '4');
    expect(last.searchParams.get('status')).toBe('finished');
    expect(last.searchParams.get('ordering')).toBe('title');
    expect(
      within(screen.getByRole('combobox', { name: 'Rating' }))
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Any rating', '5★', '4★ and up', '3★ and up', '2★ and up', 'Unrated']);
  });

  it('offers author and rating sorts', async () => {
    const requests = setup(() => [shelfEntry({ status: 'reading' })]);
    renderApp('/shelf');
    await screen.findByRole('link', { name: 'Project Hail Mary' });
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Sort by' }), 'author');
    await waitForRequest(requests, (u) => u.searchParams.get('ordering') === 'author');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Sort by' }), 'rating');
    await waitForRequest(requests, (u) => u.searchParams.get('ordering') === '-rating');
  });

  it('names the author filter and clears it, keeping focus on the page', async () => {
    const requests = setup(() => [shelfEntry({ status: 'finished' })]);
    renderApp('/shelf?status=finished&author=9&rating=4');
    expect(await screen.findByText(/By Mara Vell/)).toBeInTheDocument();
    expect(requests[0].searchParams.get('author')).toBe('9');

    await userEvent.setup().click(screen.getByRole('button', { name: 'Clear the author filter' }));
    const last = await waitForRequest(requests, (u) => !u.searchParams.has('author'));
    expect(last.searchParams.get('rating')).toBe('4'); // the other filter stays
    expect(screen.queryByText(/By Mara Vell/)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveFocus();
  });

  it('says when nothing matches the filters, with a way to clear them', async () => {
    const requests = setup(() => []);
    renderApp('/shelf?status=finished&rating=unrated');
    expect(await screen.findByText(/No finished books match these filters/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitForRequest(requests, (u) => !u.searchParams.has('rating'));
    expect(
      await screen.findByText("You haven't finished any books yet.", { exact: false }),
    ).toBeInTheDocument();
  });

  it('ignores a malformed author id in the URL', async () => {
    const requests = setup(() => []);
    renderApp('/shelf?author=abc');
    await screen.findByText(/not reading anything/);
    expect(requests[0].searchParams.has('author')).toBe(false);
  });

  it('keeps the filters when switching shelves in the shelf bar', async () => {
    setup(() => []);
    renderApp('/shelf?status=finished&sort=author&author=9&rating=4');
    await screen.findByText(/By Mara Vell/);
    expect(
      within(screen.getByRole('navigation', { name: 'Shelves' })).getByRole('link', {
        name: 'Reading',
      }),
    ).toHaveAttribute('href', '/shelf?status=reading&sort=author&author=9&rating=4');
  });
});

async function waitForRequest(requests: URL[], match: (url: URL) => boolean): Promise<URL> {
  let found: URL | undefined;
  await waitFor(() => {
    found = [...requests].reverse().find(match);
    expect(found).toBeDefined();
  });
  return found as URL;
}
