/** Parses a whole number of pages from 1 up, or returns an error message. */
export function parsePages(value: string): number | string {
  if (!/^\d+$/.test(value.trim())) return 'Enter a whole number of pages.';
  const pages = Number(value);
  return pages >= 1 ? pages : 'Log at least 1 page.';
}
