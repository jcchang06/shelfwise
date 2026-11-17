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

const DATE_FORMAT = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
});

/**
 * "2025-03-09" -> "Mar 9, 2025". Parsed and formatted as UTC so a date-only value never
 * shifts a day in the browser's time zone.
 */
export function formatDate(isoDate: string): string {
  return DATE_FORMAT.format(new Date(`${isoDate}T00:00:00Z`));
}

/** A timestamp ("2026-11-16T20:15:00Z") as the reader's local calendar day. */
export function formatTimestampDate(isoTimestamp: string): string {
  return formatDate(localDateISO(new Date(isoTimestamp)));
}
