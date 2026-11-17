import { useInfiniteQuery } from '@tanstack/react-query';

import { MIN_QUERY_LENGTH, searchBooks } from '../api/books';

export const searchKey = (q: string) => ['search', q] as const;

/** Pages of results for `q`; "More results" fetches the next page and appends it. */
export function useBookSearch(q: string) {
  return useInfiniteQuery({
    queryKey: searchKey(q),
    queryFn: ({ pageParam }) => searchBooks(q, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage) => lastPage.next_page ?? undefined,
    enabled: q.length >= MIN_QUERY_LENGTH,
    staleTime: 5 * 60_000,
  });
}
