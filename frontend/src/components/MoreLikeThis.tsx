import { useSimilarBooks } from '../hooks/useRecommendations';
import { SuggestedBookItem } from './SuggestedBookItem';

/** "More like this" on a book page (R-3). Hidden while loading, on error, or when empty. */
export function MoreLikeThis({
  bookId,
  onAdded,
}: {
  bookId: number;
  onAdded: (message: string) => void;
}) {
  const similar = useSimilarBooks(bookId);
  const books = similar.data?.results ?? [];
  if (!books.length) return null;
  return (
    <section aria-labelledby="more-like-this-title" className="more-like-this">
      <h2 id="more-like-this-title">More like this</h2>
      <ul className="suggestions">
        {books.map((book) => (
          <SuggestedBookItem key={book.id} book={book} onAdded={onAdded} headingLevel={3} />
        ))}
      </ul>
    </section>
  );
}
