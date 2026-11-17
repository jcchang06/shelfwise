import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getBook } from '../api/books';
import {
  getShelfEntryForBook,
  listShelf,
  removeShelfEntry,
  updateShelfEntry,
  type ShelfChanges,
  type ShelfFilters,
  type ShelfSort,
} from '../api/shelf';
import type { ShelfEntry, ShelfStatus } from '../api/types';

export const shelfListKey = (status: ShelfStatus, sort: ShelfSort, filters: ShelfFilters) =>
  ['shelf', 'list', status, sort, filters.author, filters.rating] as const;
export const shelfEntryKey = (bookId: number) => ['shelf', 'book', bookId] as const;
export const bookKey = (bookId: number) => ['book', bookId] as const;

export function useShelfList(status: ShelfStatus, sort: ShelfSort, filters: ShelfFilters) {
  return useInfiniteQuery({
    queryKey: shelfListKey(status, sort, filters),
    queryFn: ({ pageParam }) => listShelf(status, sort, filters, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _all, lastPageParam) =>
      lastPage.next ? lastPageParam + 1 : undefined,
  });
}

export function useBook(bookId: number) {
  return useQuery({
    queryKey: bookKey(bookId),
    queryFn: () => getBook(bookId),
    enabled: bookId > 0,
  });
}

/** The caller's shelf entry for a book; `data` is null when it isn't on the shelf. */
export function useShelfEntry(bookId: number) {
  return useQuery({
    queryKey: shelfEntryKey(bookId),
    queryFn: () => getShelfEntryForBook(bookId),
    enabled: bookId > 0,
  });
}

/** Everything that shows shelf data changes when an entry does. */
function refreshAfterShelfChange(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ['shelf', 'list'] });
  void queryClient.invalidateQueries({ queryKey: ['stats'] });
  void queryClient.invalidateQueries({ queryKey: ['search'] }); // results show shelf status
}

export function useUpdateShelfEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entry, changes }: { entry: ShelfEntry; changes: ShelfChanges }) =>
      updateShelfEntry(entry.id, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData(shelfEntryKey(updated.book.id), updated);
      refreshAfterShelfChange(queryClient);
    },
  });
}

export function useRemoveShelfEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entry: ShelfEntry) => removeShelfEntry(entry.id),
    onSuccess: (_result, entry) => {
      queryClient.setQueryData(shelfEntryKey(entry.book.id), null);
      void queryClient.invalidateQueries({ queryKey: ['logs'] }); // removal deletes them
      refreshAfterShelfChange(queryClient);
    },
  });
}
