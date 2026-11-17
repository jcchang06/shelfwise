/**
 * Plain-language summaries of each chart, used as the figure caption and the canvas's
 * accessible name (charts need a text alternative). Pure functions, tested directly.
 */

import type { Stats } from '../../api/stats';

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

export const fmt = (n: number) => n.toLocaleString('en-US');
const plural = (n: number, one: string, many = `${one}s`) => `${fmt(n)} ${n === 1 ? one : many}`;

export const DATE_UNKNOWN = 'Date unknown';

export function monthName(month: string): string {
  return MONTHS[Number(month.slice(5, 7)) - 1] ?? month;
}

export function pagesSummary(year: number, rows: Stats['pages_per_month']): string {
  const total = rows.reduce((sum, r) => sum + r.pages, 0);
  if (total === 0) return `No pages logged in ${year} yet.`;
  const best = rows.reduce((a, b) => (b.pages > a.pages ? b : a));
  const dnf = rows.reduce((sum, r) => sum + r.dnf_pages, 0);
  let text = `${plural(total, 'page')} in ${year}, most in ${monthName(best.month)} (${fmt(best.pages)}).`;
  if (dnf > 0) text += ` ${fmt(dnf)} ${dnf === 1 ? 'was' : 'were'} from books you didn't finish.`;
  return text;
}

export function booksPerYearSummary(rows: Stats['books_per_year']): string {
  const dated = rows.filter((r) => r.year !== null);
  const finished = rows.reduce((sum, r) => sum + r.finished, 0);
  const dnf = rows.reduce((sum, r) => sum + r.dnf, 0);
  if (finished + dnf === 0) return 'No finished or DNF books yet.';
  const parts: string[] = [];
  const best = dated.reduce<(typeof dated)[number] | null>(
    (a, b) => (a === null || b.finished > a.finished ? b : a),
    null,
  );
  parts.push(`${plural(finished, 'book')} finished in total`);
  if (best && best.finished > 0) parts[0] += `, most in ${best.year} (${fmt(best.finished)})`;
  parts[0] += '.';
  if (dnf > 0) parts.push(`${fmt(dnf)} marked DNF.`);
  const unknown = rows.find((r) => r.year === null);
  if (unknown && unknown.finished + unknown.dnf > 0) {
    parts.push(`${plural(unknown.finished + unknown.dnf, 'book')} with no date.`);
  }
  return parts.join(' ');
}

export function genreSummary(year: number, rows: Stats['genre_mix']): string {
  if (rows.length === 0) return `No genres for books finished or stopped in ${year}.`;
  const named = rows.filter((r) => r.genre !== 'Other');
  const topFinished = named.reduce<(typeof named)[number] | null>(
    (a, b) => (a === null || b.finished > a.finished ? b : a),
    null,
  );
  const topDnf = named.reduce<(typeof named)[number] | null>(
    (a, b) => (a === null || b.dnf > a.dnf ? b : a),
    null,
  );
  const parts: string[] = [];
  if (topFinished && topFinished.finished > 0) {
    parts.push(
      `${topFinished.genre} leads in ${year} with ${plural(topFinished.finished, 'finished book')}.`,
    );
  }
  if (topDnf && topDnf.dnf > 0) parts.push(`Most DNFs: ${topDnf.genre} (${fmt(topDnf.dnf)}).`);
  return parts.join(' ') || `Genres for ${year}.`;
}

export function ratingsSummary(
  year: number,
  rows: Stats['rating_distribution'],
  average: number | null,
): string {
  const rated = rows.reduce((sum, r) => sum + r.books, 0);
  if (rated === 0 || average === null) return `No books rated in ${year} yet.`;
  const common = rows.reduce((a, b) => (b.books > a.books ? b : a));
  return `${plural(rated, 'book')} rated in ${year}, average ${average.toFixed(1)}. Most often ${plural(common.stars, 'star')} (${fmt(common.books)}).`;
}
