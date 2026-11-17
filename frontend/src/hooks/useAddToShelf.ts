import { useMutation, useQueryClient, type InfiniteData } from '@tanstack/react-query';

import { addToShelf, type AddToShelfPayload } from '../api/shelf';
import type { SearchResponse, SearchResult, ShelfEntry } from '../api/types';

/**
 * Adds a search result to the shelf. On success the result is updated in every cached
 * search (book_id + shelf), so it shows "On your shelf" without refetching; shelf and
 * stats queries are invalidated for when those pages exist.
 */
export function useAddToShelf() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ payload }: { result: SearchResult; payload: AddToShelfPayload }) =>
      addToShelf(payload),
    onSuccess: (entry: ShelfEntry, { result }) => {
      queryClient.setQueriesData<InfiniteData<SearchResponse>>({ queryKey: ['search'] }, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                results: page.results.map((r) =>
                  r.source === result.source && r.source_id === result.source_id
                    ? {
                        ...r,
                        book_id: entry.book.id,
                        shelf: { id: entry.id, status: entry.status },
                      }
                    : r,
                ),
              })),
            }
          : data,
      );
      void queryClient.invalidateQueries({ queryKey: ['shelf'] });
      void queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });
}
