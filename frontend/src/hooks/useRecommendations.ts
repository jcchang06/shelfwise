import { useQuery } from '@tanstack/react-query';

import { getRecommendations, getSimilarBooks } from '../api/recommendations';

export const recommendationsKey = ['recommendations'] as const;
export const similarKey = (bookId: number) => ['similar', bookId] as const;

/** The reader's picks: precomputed nightly, so this is a plain read. */
export function useRecommendations() {
  return useQuery({ queryKey: recommendationsKey, queryFn: getRecommendations });
}

/** "More like this" for a book. Never retried: a failure just hides the section. */
export function useSimilarBooks(bookId: number) {
  return useQuery({
    queryKey: similarKey(bookId),
    queryFn: () => getSimilarBooks(bookId),
    enabled: bookId > 0,
    retry: false,
  });
}
