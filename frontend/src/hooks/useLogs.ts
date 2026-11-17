import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import {
  deleteLog,
  listLogs,
  logPages,
  updateLog,
  type LogChanges,
  type LogPagesPayload,
  type LogShelfEntry,
  type ReadingLog,
} from '../api/logs';
import type { ShelfEntry } from '../api/types';
import { shelfEntryKey } from './useShelf';

export const logsKey = (bookId: number) => ['logs', bookId] as const;

/** This book's logs, newest day first; "Show older logs" fetches the next page. */
export function useBookLogs(bookId: number) {
  return useInfiniteQuery({
    queryKey: logsKey(bookId),
    queryFn: ({ pageParam }) => listLogs(bookId, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _all, lastPageParam) =>
      lastPage.next ? lastPageParam + 1 : undefined,
    enabled: bookId > 0,
  });
}

type QueryClient = ReturnType<typeof useQueryClient>;

/**
 * After a log write: fold the returned shelf fields (status, started_at, pages_logged)
 * into the cached entry right away, then refresh everything that shows logs or progress.
 */
function afterLogWrite(
  queryClient: QueryClient,
  bookId: number,
  shelf: LogShelfEntry | null,
  logCountDelta: number,
) {
  queryClient.setQueryData<ShelfEntry | null>(shelfEntryKey(bookId), (entry) =>
    entry
      ? {
          ...entry,
          ...(shelf ?? {}),
          reading_log_count: Math.max(0, entry.reading_log_count + logCountDelta),
        }
      : entry,
  );
  void queryClient.invalidateQueries({ queryKey: logsKey(bookId) });
  void queryClient.invalidateQueries({ queryKey: shelfEntryKey(bookId) });
  void queryClient.invalidateQueries({ queryKey: ['shelf', 'list'] });
  void queryClient.invalidateQueries({ queryKey: ['stats'] });
}

export function useLogPages() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LogPagesPayload) => logPages(payload),
    onSuccess: (response, payload) => {
      // A new day is a new row; an existing day just grew. (The 201/200 isn't exposed,
      // so tell them apart by whether the total equals what was just logged.)
      const isNewDay = response.pages_read === payload.pages_read;
      afterLogWrite(queryClient, payload.book_id, response.shelf_entry, isNewDay ? 1 : 0);
    },
  });
}

export function useUpdateLog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ log, changes }: { log: ReadingLog; changes: LogChanges }) =>
      updateLog(log.id, changes),
    onSuccess: (response, { log }) =>
      afterLogWrite(queryClient, log.book_id, response.shelf_entry, 0),
  });
}

export function useDeleteLog() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (log: ReadingLog) => deleteLog(log.id),
    onSuccess: (_result, log) => afterLogWrite(queryClient, log.book_id, null, -1),
  });
}
