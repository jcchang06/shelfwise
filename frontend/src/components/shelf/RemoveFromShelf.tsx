import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { formError } from '../../api/errors';
import type { ShelfEntry } from '../../api/types';
import { useRemoveShelfEntry } from '../../hooks/useShelf';
import type { ShelfLocationState } from '../../pages/ShelfPage';
import { ConfirmDialog } from '../ConfirmDialog';

/** Remove from shelf, after a confirmation that says how many logs go with it (T-2). */
export function RemoveFromShelf({ entry }: { entry: ShelfEntry }) {
  const [open, setOpen] = useState(false);
  const remove = useRemoveShelfEntry();
  const navigate = useNavigate();
  const logs = entry.reading_log_count;

  function confirm() {
    remove.mutate(entry, {
      onSuccess: () => {
        setOpen(false);
        const state: ShelfLocationState = {
          announce: `Removed ${entry.book.title} from your shelf.`,
        };
        navigate('/shelf', { state });
      },
    });
  }

  return (
    <div className="panel">
      <button type="button" className="button-danger" onClick={() => setOpen(true)}>
        Remove from shelf
      </button>
      <ConfirmDialog
        open={open}
        title={`Remove ${entry.book.title} from your shelf?`}
        confirmLabel="Remove"
        busy={remove.isPending}
        onConfirm={confirm}
        onCancel={() => setOpen(false)}
      >
        <p>
          {logs > 0
            ? `This also deletes your ${logs} reading ${logs === 1 ? 'log' : 'logs'} for this book.`
            : "You haven't logged any pages for this book."}{' '}
          The book stays in the catalog, so you can add it again later.
        </p>
        {remove.isError ? (
          <p className="field-error" role="alert">
            {formError(remove.error)}
          </p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
