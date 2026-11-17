interface ReadingProgressProps {
  pagesLogged: number;
  pageCount: number | null;
}

/**
 * "120 of 496 pages (24%)" with a bar. Logged pages can exceed the page count (editions
 * differ, or a miscount), so the bar and percentage are capped at 100% while the text
 * keeps the real number: "512 of 496 pages (100%)".
 */
export function ReadingProgress({ pagesLogged, pageCount }: ReadingProgressProps) {
  if (!pageCount) {
    return (
      <p className="progress-text">
        {pagesLogged} {pagesLogged === 1 ? 'page' : 'pages'} logged
      </p>
    );
  }
  const shown = Math.min(pagesLogged, pageCount);
  const percent = Math.round((shown / pageCount) * 100);
  return (
    <div className="progress">
      <progress value={shown} max={pageCount} aria-label="Reading progress" />
      <span className="progress-text">
        {pagesLogged} of {pageCount} pages ({percent}%)
      </span>
    </div>
  );
}
