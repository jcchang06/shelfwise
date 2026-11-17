import { describe, expect, it } from 'vitest';

import {
  booksPerYearSummary,
  genreSummary,
  monthName,
  pagesSummary,
  ratingsSummary,
} from './summaries';

const months = (pages: number[], dnf: number[] = []) =>
  pages.map((p, i) => ({
    month: `2026-${String(i + 1).padStart(2, '0')}`,
    pages: p,
    dnf_pages: dnf[i] ?? 0,
  }));

describe('pagesSummary', () => {
  it('names the total, the best month and the DNF share', () => {
    const rows = months([600, 400, 1020, 0, 0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 40]);
    expect(pagesSummary(2026, rows)).toBe(
      "2,020 pages in 2026, most in March (1,020). 40 were from books you didn't finish.",
    );
  });

  it('uses singulars and skips the DNF sentence when there are none', () => {
    expect(pagesSummary(2026, months([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))).toBe(
      '1 page in 2026, most in January (1).',
    );
    expect(pagesSummary(2026, months([5], [1]))).toContain('1 was from books');
  });

  it('says when nothing is logged', () => {
    expect(pagesSummary(2025, months(Array(12).fill(0)))).toBe('No pages logged in 2025 yet.');
  });
});

describe('booksPerYearSummary', () => {
  it('summarises totals, the best year, DNFs and undated books', () => {
    expect(
      booksPerYearSummary([
        { year: 2025, finished: 18, dnf: 3 },
        { year: 2026, finished: 21, dnf: 4 },
        { year: null, finished: 2, dnf: 0 },
      ]),
    ).toBe('41 books finished in total, most in 2026 (21). 7 marked DNF. 2 books with no date.');
  });

  it('handles nothing yet', () => {
    expect(booksPerYearSummary([])).toBe('No finished or DNF books yet.');
  });
});

describe('genreSummary', () => {
  it('names the leading genre and the most-DNFed genre, ignoring Other', () => {
    expect(
      genreSummary(2026, [
        { genre: 'Science Fiction', finished: 7, dnf: 1 },
        { genre: 'Romance', finished: 1, dnf: 2 },
        { genre: 'Other', finished: 9, dnf: 5 },
      ]),
    ).toBe('Science Fiction leads in 2026 with 7 finished books. Most DNFs: Romance (2).');
  });

  it('handles no genres', () => {
    expect(genreSummary(2026, [])).toBe('No genres for books finished or stopped in 2026.');
  });
});

describe('ratingsSummary', () => {
  const rows = [
    { stars: 1, books: 0 },
    { stars: 2, books: 1 },
    { stars: 3, books: 2 },
    { stars: 4, books: 5 },
    { stars: 5, books: 4 },
  ];

  it('gives the count, average and most common rating', () => {
    expect(ratingsSummary(2026, rows, 3.9)).toBe(
      '12 books rated in 2026, average 3.9. Most often 4 stars (5).',
    );
  });

  it('handles nothing rated', () => {
    expect(
      ratingsSummary(
        2026,
        rows.map((r) => ({ ...r, books: 0 })),
        null,
      ),
    ).toBe('No books rated in 2026 yet.');
  });
});

it('monthName', () => {
  expect(monthName('2026-01')).toBe('January');
  expect(monthName('2026-12')).toBe('December');
});
