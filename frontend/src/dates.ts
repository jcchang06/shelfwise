/**
 * Today's date as YYYY-MM-DD in the *browser's* time zone. Not toISOString(), which is
 * UTC and would say "tomorrow" every evening in the Americas.
 */
export function localDateISO(date: Date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** "2014-03-05" / "2014-03" / "2014" -> "2014". */
export function yearOf(partialDate: string): string {
  return partialDate.slice(0, 4);
}
