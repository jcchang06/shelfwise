import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';

import { setRefreshToken } from '../api/tokens';
import type { SearchResponse, SearchResult, ShelfEntry } from '../api/types';
import { localDateISO } from '../dates';
import { renderApp } from '../test/renderApp';
import { api, authHandlers, server } from '../test/server';

function result(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    source: 'google_books',
    source_id: 'vol1',
    title: 'Project Hail Mary',
    authors: ['Andy Weir'],
    description: 'A lone astronaut must save the earth.',
    genres: ['Science Fiction'],
    page_count: 496,
    published_date: '2021-05-04',
    isbn_13: '9780593135204',
    cover_url: 'https://books.google.com/books/content?id=vol1',
    book_id: null,
    shelf: null,
    author_links: [{ id: null, name: 'Andy Weir' }],
    ...overrides,
  };
}

function page(results: SearchResult[], overrides: Partial<SearchResponse> = {}): SearchResponse {
  return { source: 'google_books', page: 1, next_page: null, results, ...overrides };
}

function entry(overrides: Partial<ShelfEntry> = {}): ShelfEntry {
  return {
    id: 7,
    book: {
      id: 42,
      title: 'Project Hail Mary',
      authors: ['Andy Weir'],
      author_links: [{ id: 1, name: 'Andy Weir' }],
      cover_url: '',
      page_count: 496,
    },
    status: 'want_to_read',
    rating: null,
    review: '',
    started_at: null,
    finished_at: null,
    dnf_page: null,
    dnf_at: null,
    dnf_reason: '',
    dnf_note: '',
    pages_logged: 0,
    reading_log_count: 0,
    created_at: '2026-11-16T00:00:00Z',
    updated_at: '2026-11-16T00:00:00Z',
    ...overrides,
  };
}

/** Logged in, with search answered by `respond`; returns the search URLs requested. */
function setup(respond: (url: URL) => Response) {
  setRefreshToken('refresh-1');
  const searches: URL[] = [];
  server.use(
    ...authHandlers(),
    http.get(api('/books/search/'), ({ request }) => {
      const url = new URL(request.url);
      searches.push(url);
      return respond(url);
    }),
  );
  return searches;
}

/** Captures POST /api/shelf/ bodies and answers with `respond`. */
function captureAdds(respond: () => Response = () => HttpResponse.json(entry(), { status: 201 })) {
  const bodies: unknown[] = [];
  server.use(
    http.post(api('/shelf/'), async ({ request }) => {
      bodies.push(await request.json());
      return respond();
    }),
  );
  return bodies;
}

const resultItem = (title: string) =>
  screen.getByRole('heading', { name: title, level: 2 }).closest('li') as HTMLElement;

describe('searching', () => {
  it('runs the query from the URL and shows Google results with attribution', async () => {
    const searches = setup(() => HttpResponse.json(page([result()])));
    renderApp('/search?q=project%20hail%20mary');

    expect(await screen.findByRole('heading', { name: 'Project Hail Mary' })).toBeInTheDocument();
    expect(searches[0].searchParams.get('q')).toBe('project hail mary');
    expect(screen.getByRole('searchbox', { name: 'Title, author or ISBN' })).toHaveValue(
      'project hail mary',
    );
    // Google's branding rules: logo next to the results, the wording, and a link per book.
    expect(screen.getByText('Google Books search results')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Powered by Google' })).toHaveAttribute(
      'src',
      'https://books.google.com/googlebooks/images/poweredby.png',
    );
    expect(
      within(resultItem('Project Hail Mary')).getByRole('link', {
        name: 'View Project Hail Mary on Google Books (opens in a new tab)',
      }),
    ).toHaveAttribute('href', 'https://books.google.com/books?id=vol1');
    expect(screen.getByText('Andy Weir · 2021 · 496 pages')).toBeInTheDocument();
    expect(
      screen.getByText(/1 Google Books search results for “project hail mary”/),
    ).toBeInTheDocument();
  });

  it('credits Open Library when results come from the fallback', async () => {
    setup(() =>
      HttpResponse.json(
        page([result({ source: 'open_library', source_id: 'OL1W' })], { source: 'open_library' }),
      ),
    );
    renderApp('/search?q=dune');
    expect(await screen.findByRole('link', { name: 'Open Library' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Powered by Google' })).not.toBeInTheDocument();
    expect(
      screen.getByRole('link', {
        name: 'View Project Hail Mary on Open Library (opens in a new tab)',
      }),
    ).toHaveAttribute('href', 'https://openlibrary.org/works/OL1W');
  });

  it('searches on submit and puts the query in the URL', async () => {
    const searches = setup(() => HttpResponse.json(page([result()])));
    renderApp('/search');
    expect(await screen.findByText(/search by title, author or isbn to add/i)).toBeInTheDocument();
    expect(searches).toHaveLength(0);

    const user = userEvent.setup();
    await user.type(screen.getByRole('searchbox'), '  hail mary ');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    await screen.findByRole('heading', { name: 'Project Hail Mary' });
    expect(searches).toHaveLength(1);
    expect(searches[0].searchParams.get('q')).toBe('hail mary');
  });

  it('rejects queries under 2 characters without a request', async () => {
    const searches = setup(() => HttpResponse.json(page([])));
    renderApp('/search');
    const user = userEvent.setup();
    await user.type(await screen.findByRole('searchbox'), 'a');
    await user.click(screen.getByRole('button', { name: 'Search' }));

    expect(screen.getByRole('searchbox')).toHaveAccessibleDescription(
      'Enter at least 2 characters.',
    );
    expect(searches).toHaveLength(0);
  });

  it('suggests the ISBN when nothing is found', async () => {
    setup(() => HttpResponse.json(page([])));
    renderApp('/search?q=qzxqv');
    expect(
      await screen.findByText('No books found for “qzxqv”. Try the ISBN.'),
    ).toBeInTheDocument();
  });

  it.each([
    [
      503,
      { detail: 'Book search is temporarily unavailable. Please try again in a few minutes.' },
      /temporarily unavailable/,
    ],
    [429, { detail: 'Request was throttled. Expected available in 30 seconds.' }, /throttled/],
  ])('shows the %s error', async (status, body, message) => {
    setup(() => HttpResponse.json(body, { status }));
    renderApp('/search?q=dune');
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
  });

  it('shows a 400 on the search field', async () => {
    setup(() =>
      HttpResponse.json(
        { q: ['Ensure this field has no more than 200 characters.'] },
        { status: 400 },
      ),
    );
    renderApp(`/search?q=${'x'.repeat(201)}`);
    await waitFor(() =>
      expect(screen.getByRole('searchbox')).toHaveAccessibleDescription(
        'Ensure this field has no more than 200 characters.',
      ),
    );
  });

  it('loads more results onto the end of the list', async () => {
    const searches = setup((url) =>
      url.searchParams.get('page') === '2'
        ? HttpResponse.json(page([result({ source_id: 'vol2', title: 'Artemis' })], { page: 2 }))
        : HttpResponse.json(page([result()], { next_page: 2 })),
    );
    renderApp('/search?q=andy%20weir');
    await screen.findByRole('heading', { name: 'Project Hail Mary' });

    await userEvent.setup().click(screen.getByRole('button', { name: 'More results' }));

    expect(await screen.findByRole('heading', { name: 'Artemis' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Project Hail Mary' })).toBeInTheDocument();
    expect(searches.map((u) => u.searchParams.get('page'))).toEqual(['1', '2']);
    expect(screen.queryByRole('button', { name: 'More results' })).not.toBeInTheDocument();
  });
});

describe('author links', () => {
  it('links authors in the catalog to their page and leaves the rest as text', async () => {
    setup(() =>
      HttpResponse.json(
        page([
          result({
            authors: ['Andy Weir', 'Guest Writer'],
            author_links: [
              { id: 1, name: 'Andy Weir' },
              { id: null, name: 'Guest Writer' },
            ],
          }),
        ]),
      ),
    );
    renderApp('/search?q=hail');
    const item = (await screen.findByRole('heading', { name: 'Project Hail Mary' })).closest(
      'li',
    ) as HTMLElement;
    expect(within(item).getByRole('link', { name: 'Andy Weir' })).toHaveAttribute(
      'href',
      '/authors/1',
    );
    expect(within(item).queryByRole('link', { name: 'Guest Writer' })).not.toBeInTheDocument();
    expect(within(item).getByText(/Guest Writer/)).toBeInTheDocument();
  });
});

describe('adding to the shelf', () => {
  it('shows books already on my shelf with their status and no add form', async () => {
    setup(() =>
      HttpResponse.json(page([result({ book_id: 42, shelf: { id: 7, status: 'reading' } })])),
    );
    renderApp('/search?q=hail');
    const item = await screen.findByText('On your shelf · Reading');
    expect(screen.getByRole('link', { name: 'On your shelf · Reading' })).toHaveAttribute(
      'href',
      '/books/42',
    );
    expect(
      within(item.closest('li') as HTMLElement).queryByRole('button', { name: 'Add' }),
    ).toBeNull();
  });

  it('adds a new book by source and marks it on the shelf', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds();
    renderApp('/search?q=hail');
    await screen.findByRole('heading', { name: 'Project Hail Mary' });

    await userEvent.setup().click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Want to read')).toBeInTheDocument();
    expect(adds).toEqual([{ source: 'google_books', source_id: 'vol1', status: 'want_to_read' }]);
    expect(screen.getByText('Added Project Hail Mary to Want to read.')).toBeInTheDocument();
  });

  it('sends book_id when the result is already in the catalog', async () => {
    setup(() => HttpResponse.json(page([result({ book_id: 42 })])));
    const adds = captureAdds(() =>
      HttpResponse.json(entry({ status: 'reading' }), { status: 201 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(
      await screen.findByRole('combobox', { name: 'Shelf for Project Hail Mary' }),
      'reading',
    );
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Reading')).toBeInTheDocument();
    expect(adds).toEqual([{ book_id: 42, status: 'reading' }]);
  });

  it('offers every shelf, DNF included', async () => {
    setup(() => HttpResponse.json(page([result()])));
    renderApp('/search?q=hail');
    const select = await screen.findByRole('combobox', { name: 'Shelf for Project Hail Mary' });
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Want to read', 'Reading', 'Finished', 'Did not finish']);
  });

  it('adds as DNF with only defaults: reason, page and note left out', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds(() =>
      HttpResponse.json(entry({ status: 'dnf', dnf_reason: 'not_specified' }), { status: 201 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'dnf');

    expect(screen.getByRole('combobox', { name: 'Why did you stop? (optional)' })).toHaveValue('');
    expect(screen.getByLabelText('Stopped on (optional)')).toHaveValue(localDateISO());
    expect(screen.getByLabelText('Stopped at page (optional)')).toHaveValue(null); // no logs yet
    expect(screen.getByLabelText('Note (optional)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Did not finish')).toBeInTheDocument();
    expect(adds).toEqual([
      { source: 'google_books', source_id: 'vol1', status: 'dnf', dnf_at: localDateISO() },
    ]);
  });

  it('adds as DNF with a reason, page, date and note', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds(() =>
      HttpResponse.json(entry({ status: 'dnf', dnf_reason: 'pacing' }), { status: 201 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'dnf');
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Why did you stop? (optional)' }),
      'pacing',
    );
    await user.type(screen.getByLabelText('Stopped at page (optional)'), '45');
    const date = screen.getByLabelText('Stopped on (optional)');
    await user.clear(date);
    await user.type(date, '2026-11-01');
    await user.type(screen.getByLabelText('Note (optional)'), 'Too slow');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Did not finish')).toBeInTheDocument();
    expect(adds).toEqual([
      {
        source: 'google_books',
        source_id: 'vol1',
        status: 'dnf',
        dnf_reason: 'pacing',
        dnf_page: 45,
        dnf_at: '2026-11-01',
        dnf_note: 'Too slow',
      },
    ]);
  });

  it('shows an API error on the DNF page field and moves focus there', async () => {
    setup(() => HttpResponse.json(page([result()])));
    captureAdds(() =>
      HttpResponse.json({ dnf_page: ['This book has only 496 pages.'] }, { status: 400 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'dnf');
    const pageField = screen.getByLabelText('Stopped at page (optional)');
    await user.type(pageField, '900');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(pageField).toHaveFocus());
    expect(pageField).toHaveAccessibleDescription('This book has only 496 pages.');
    expect(screen.getByRole('button', { name: 'Add' })).toBeEnabled();
  });

  it('rejects a future DNF date without a request', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds();
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'dnf');
    const date = screen.getByLabelText('Stopped on (optional)');
    await user.clear(date);
    await user.type(date, '2999-01-01');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(date).toHaveAccessibleDescription("This date can't be in the future.");
    expect(date).toHaveFocus();
    expect(adds).toHaveLength(0);
  });

  it('sends the finished-on date, defaulting to today', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds(() =>
      HttpResponse.json(entry({ status: 'finished', finished_at: '2019-06-01' }), { status: 201 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'finished');

    const date = screen.getByLabelText('Finished on (optional)');
    expect(date).toHaveValue(localDateISO());
    expect(date).toHaveAttribute('max', localDateISO());

    await user.clear(date);
    await user.type(date, '2019-06-01');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Finished')).toBeInTheDocument();
    expect(adds).toEqual([
      { source: 'google_books', source_id: 'vol1', status: 'finished', finished_at: '2019-06-01' },
    ]);
  });

  it('leaves a cleared finished-on date out, so the API uses today', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds(() =>
      HttpResponse.json(entry({ status: 'finished' }), { status: 201 }),
    );
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'finished');
    await user.clear(screen.getByLabelText('Finished on (optional)'));
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(await screen.findByText('On your shelf · Finished')).toBeInTheDocument();
    expect(adds).toEqual([{ source: 'google_books', source_id: 'vol1', status: 'finished' }]);
  });

  it('rejects a future finished-on date without a request', async () => {
    setup(() => HttpResponse.json(page([result()])));
    const adds = captureAdds();
    renderApp('/search?q=hail');
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole('combobox'), 'finished');
    const date = screen.getByLabelText('Finished on (optional)');
    await user.clear(date);
    await user.type(date, '2999-01-01');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    expect(date).toHaveAccessibleDescription("The finish date can't be in the future.");
    expect(date).toHaveFocus();
    expect(adds).toHaveLength(0);
  });

  it('treats 409 "already on your shelf" as done, not as an error', async () => {
    setup(() => HttpResponse.json(page([result()])));
    captureAdds(() =>
      HttpResponse.json({ detail: 'This book is already on your shelf.', id: 7 }, { status: 409 }),
    );
    renderApp('/search?q=hail');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Add' }));

    expect(await screen.findByText('Already on your shelf')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows a failed add on that result only', async () => {
    setup(() =>
      HttpResponse.json(page([result(), result({ source_id: 'vol2', title: 'Artemis' })])),
    );
    captureAdds(() =>
      HttpResponse.json(
        { detail: "Couldn't reach the book source to add this book. Please try again shortly." },
        { status: 503 },
      ),
    );
    renderApp('/search?q=andy');
    await screen.findByRole('heading', { name: 'Artemis' });

    await userEvent
      .setup()
      .click(within(resultItem('Project Hail Mary')).getByRole('button', { name: 'Add' }));

    expect(await within(resultItem('Project Hail Mary')).findByRole('alert')).toHaveTextContent(
      /couldn't reach the book source/i,
    );
    expect(within(resultItem('Artemis')).queryByRole('alert')).not.toBeInTheDocument();
    expect(
      within(resultItem('Project Hail Mary')).getByRole('button', { name: 'Add' }),
    ).toBeEnabled();
  });
});

describe('navigation', () => {
  it('has a Search link in the main navigation', async () => {
    setup(() => HttpResponse.json(page([])));
    renderApp('/search');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Search' })).toHaveAttribute('href', '/search');
  });
});
