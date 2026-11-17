import { useState } from 'react';

interface BookCoverProps {
  url: string;
  size?: 'small' | 'medium';
}

/**
 * A book cover with a fixed box (no layout shift while it loads) and a plain placeholder
 * when there's no cover or it fails to load. Decorative: the title is always next to it.
 */
export function BookCover({ url, size = 'small' }: BookCoverProps) {
  const [failed, setFailed] = useState(false);
  const className = `book-cover book-cover-${size}`;
  if (!url || failed) {
    return <div className={`${className} book-cover-placeholder`} aria-hidden="true" />;
  }
  return (
    <img
      className={className}
      src={url}
      alt=""
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
