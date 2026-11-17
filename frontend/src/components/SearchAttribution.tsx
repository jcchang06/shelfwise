import type { BookSource } from '../api/types';

// Google's official asset, served from books.google.com (already allowed by the CSP).
const POWERED_BY_GOOGLE = 'https://books.google.com/googlebooks/images/poweredby.png';

export function SearchAttribution({ source }: { source: BookSource }) {
  // Google's branding rules: the "powered by Google" logo adjacent to the results, and
  // the wording "Google Books search results".
  if (source === 'google_books') {
    return (
      <p className="attribution">
        <span>Google Books search results</span>
        <img src={POWERED_BY_GOOGLE} alt="Powered by Google" width={62} height={20} />
      </p>
    );
  }
  return (
    <p className="attribution">
      Results from{' '}
      <a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer">
        Open Library
      </a>
    </p>
  );
}
