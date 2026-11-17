import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { ApiError } from '../api/client';
import {
  dismissImportRow,
  getImport,
  listImportRows,
  listImports,
  processImport,
  resolveImportRow,
  uploadImport,
  type GoodreadsImport,
  type ImportRowState,
} from '../api/imports';
import type { BookReference } from '../api/shelf';

export const importsKey = ['imports'] as const;
export const importKey = (id: number) => ['imports', id] as const;
export const importRowsKey = (id: number, state: ImportRowState) =>
  ['imports', id, 'rows', state] as const;

/** How long to wait before retrying when another batch holds the import (409). */
export const BUSY_RETRY_MS = 5000;

export function isActive(goodreadsImport: GoodreadsImport | undefined): boolean {
  return goodreadsImport?.status === 'pending' || goodreadsImport?.status === 'running';
}

export function useImports() {
  return useQuery({ queryKey: importsKey, queryFn: listImports });
}

export function useImport(id: number) {
  return useQuery({ queryKey: importKey(id), queryFn: () => getImport(id), enabled: id > 0 });
}

function afterImportChange(queryClient: QueryClient, updated: GoodreadsImport) {
  queryClient.setQueryData(importKey(updated.id), updated);
  void queryClient.invalidateQueries({ queryKey: importsKey, exact: true });
}

export function useUploadImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadImport(file),
    onSuccess: (created) => afterImportChange(queryClient, created),
  });
}

/**
 * While the page is open and the import is pending or running, run batches back to back
 * (each ~20s server-side), updating the cached import after each. A 409 means someone else
 * (the nightly job or the local Celery worker) is processing: wait, refresh, try again.
 * Stops when the import is done, paused or failed, or when the page unmounts; if the page
 * closes early, the nightly job finishes the rest.
 */
export function useImportRunner(goodreadsImport: GoodreadsImport | undefined) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [busyElsewhere, setBusyElsewhere] = useState(false);
  const id = goodreadsImport?.id ?? 0;
  const active = isActive(goodreadsImport);

  useEffect(() => {
    // No "already running" guard: StrictMode mounts effects twice in development, and a
    // guard would leave nothing running. A duplicate run just gets a 409 from the server's
    // lock and waits; each run stops on its own `cancelled` flag.
    if (!id || !active) return;
    let cancelled = false;
    setError(null);

    (async () => {
      let current = goodreadsImport;
      while (!cancelled && isActive(current)) {
        try {
          current = await processImport(id);
          setBusyElsewhere(false);
          if (!cancelled) afterImportChange(queryClient, current);
        } catch (err) {
          if (cancelled) break;
          if (err instanceof ApiError && err.status === 409) {
            setBusyElsewhere(true);
            await new Promise((resolve) => setTimeout(resolve, BUSY_RETRY_MS));
            if (cancelled) break;
            current = await getImport(id).catch(() => current);
            if (current) afterImportChange(queryClient, current);
            continue;
          }
          setError(err);
          break;
        }
      }
      if (!cancelled) {
        void queryClient.invalidateQueries({ queryKey: ['imports', id, 'rows'] });
        void queryClient.invalidateQueries({ queryKey: ['shelf'] });
        void queryClient.invalidateQueries({ queryKey: ['stats'] });
      }
    })();

    return () => {
      cancelled = true;
    };
    // Restart only when the import (or whether it's active) changes, not on every count.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, active]);

  return { error, busyElsewhere };
}

export function useImportRows(id: number, state: ImportRowState, enabled = true) {
  return useInfiniteQuery({
    queryKey: importRowsKey(id, state),
    queryFn: ({ pageParam }) => listImportRows(id, state, pageParam),
    initialPageParam: 1,
    getNextPageParam: (lastPage, _all, lastPageParam) =>
      lastPage.next ? lastPageParam + 1 : undefined,
    enabled: enabled && id > 0,
  });
}

function useRowMutation<T>(
  fn: (id: number, rowId: number, arg: T) => ReturnType<typeof dismissImportRow>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ importId, rowId, arg }: { importId: number; rowId: number; arg: T }) =>
      fn(importId, rowId, arg),
    onSuccess: (result, { importId }) => {
      afterImportChange(queryClient, result.import);
      void queryClient.invalidateQueries({ queryKey: ['imports', importId, 'rows'] });
      void queryClient.invalidateQueries({ queryKey: ['shelf'] });
      void queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
    onError: (error, { importId }) => {
      // 409: someone handled it already; refresh so it disappears.
      if (error instanceof ApiError && error.status === 409) {
        void queryClient.invalidateQueries({ queryKey: ['imports', importId, 'rows'] });
      }
    },
  });
}

export function useResolveRow() {
  return useRowMutation<BookReference>((id, rowId, book) => resolveImportRow(id, rowId, book));
}

export function useDismissRow() {
  return useRowMutation<null>((id, rowId) => dismissImportRow(id, rowId));
}
