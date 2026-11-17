import { useMutation, useQueryClient, type InfiniteData } from '@tanstack/react-query';

import { addToShelf, type AddToShelfPayload } from '../api/shelf';
import type { SearchResponse, SearchResult, ShelfEntry } from '../api/types';
import { shelfEntryKey } from './useShelf';

function isSameBook(result: SearchResult, payload: AddToShelfPayload, entry: ShelfEntry) {
  if (result.book_id !== null && result.book_id === entry.book.id) return true;
  return (
    'source' in payload &&
    result.source === payload.source &&
    result.source_id === payload.source_id
  );
}

/**
 * Adds a book to the shelf, from search or the book page. On success the book is updated
 * in every cached search (book_id + shelf) so it shows "On your shelf" without
 * refetching, the book page's entry is set, and shelf lists and stats are refreshed.
 */
export function useAddToShelf() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AddToShelfPayload) => addToShelf(payload),
    onSuccess: (entry, payload) => {
      queryClient.setQueriesData<InfiniteData<SearchResponse>>({ queryKey: ['search'] }, (data) =>
        data
          ? {
              ...data,
              pages: data.pages.map((page) => ({
                ...page,
                results: page.results.map((r) =>
                  isSameBook(r, payload, entry)
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
      queryClient.setQueryData(shelfEntryKey(entry.book.id), entry);
      void queryClient.invalidateQueries({ queryKey: ['shelf', 'list'] });
      void queryClient.invalidateQueries({ queryKey: ['stats'] });
      void queryClient.invalidateQueries({ queryKey: ['author'] }); // shelf status per work
    },
  });
}
