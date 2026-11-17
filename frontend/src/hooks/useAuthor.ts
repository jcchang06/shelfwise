import { useQuery } from '@tanstack/react-query';

import { getAuthor } from '../api/authors';

export const authorKey = (id: number) => ['author', id] as const;

/** An author page. The first view may wait on Open Library (a few seconds). */
export function useAuthor(id: number) {
  return useQuery({ queryKey: authorKey(id), queryFn: () => getAuthor(id), enabled: id > 0 });
}
