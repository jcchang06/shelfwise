import { useId, useState, type FormEvent } from 'react';

import { conflictId, formError } from '../../api/errors';
import type { LogChanges, ReadingLog } from '../../api/logs';
import { formatDate, localDateISO } from '../../dates';
import { useBookLogs, useDeleteLog, useUpdateLog } from '../../hooks/useLogs';
import { ConfirmDialog } from '../ConfirmDialog';
import { describeError } from '../shelf/useFormErrors';
import { parsePages } from './parsePages';

const rowId = (logId: number) => `log-row-${logId}`;

function focusRow(logId: number) {
  document.getElementById(rowId(logId))?.focus();
}

interface LogRowProps {
  log: ReadingLog;
  loadedIds: Set<number>;
  onChanged: (message: string) => void;
}

function LogRow({ log, loadedIds, onChanged }: LogRowProps) {
  const id = useId();
  const today = localDateISO();
  const update = useUpdateLog();
  const remove = useDeleteLog();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [pages, setPages] = useState(String(log.pages_read));
  const [date, setDate] = useState(log.log_date);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const server = describeError(update.error, ['pages_read', 'log_date']);
  const errors = { ...server.fields, ...clientErrors };
  const takenId = conflictId(update.error);
  const pagesLabel = `${log.pages_read} ${log.pages_read === 1 ? 'page' : 'pages'}`;

  function startEditing() {
    setPages(String(log.pages_read));
    setDate(log.log_date);
    setClientErrors({});
    update.reset();
    setEditing(true);
  }

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problems: Record<string, string> = {};
    const parsed = parsePages(pages);
    if (typeof parsed === 'string') problems.pages_read = parsed;
    if (!date) problems.log_date = 'Choose a date.';
    else if (date > today) problems.log_date = "You can't log pages for a future day.";
    setClientErrors(problems);
    if (Object.keys(problems).length || typeof parsed === 'string') return;

    const changes: LogChanges = {};
    if (parsed !== log.pages_read) changes.pages_read = parsed;
    if (date !== log.log_date) changes.log_date = date;
    if (!Object.keys(changes).length) {
      setEditing(false);
      return;
    }
    update
      .mutateAsync({ log, changes })
      .then((saved) => {
        setEditing(false);
        onChanged(`Saved ${formatDate(saved.log_date)}: ${saved.pages_read} pages.`);
      })
      .catch(() => undefined); // shown from update.error
  }

  function confirmDelete() {
    remove
      .mutateAsync(log)
      .then(() => {
        setConfirming(false);
        onChanged(`Deleted the log for ${formatDate(log.log_date)}.`);
      })
      .catch(() => undefined);
  }

  if (editing) {
    const errorId = (field: string) => `${id}-${field}-error`;
    return (
      <li id={rowId(log.id)} tabIndex={-1} className="log-row is-editing">
        <form
          onSubmit={handleSave}
          noValidate
          aria-label={`Edit the log for ${formatDate(log.log_date)}`}
        >
          <div className="log-form-row">
            <div className="form-field">
              <label htmlFor={`${id}-pages`}>Pages read</label>
              <input
                id={`${id}-pages`}
                type="number"
                inputMode="numeric"
                min={1}
                step={1}
                value={pages}
                onChange={(event) => setPages(event.target.value)}
                aria-invalid={errors.pages_read ? true : undefined}
                aria-describedby={errors.pages_read ? errorId('pages_read') : undefined}
              />
            </div>
            <div className="form-field">
              <label htmlFor={`${id}-date`}>Date</label>
              <input
                id={`${id}-date`}
                type="date"
                value={date}
                max={today}
                onChange={(event) => setDate(event.target.value)}
                aria-invalid={errors.log_date ? true : undefined}
                aria-describedby={errors.log_date ? errorId('log_date') : undefined}
              />
            </div>
            <button type="submit" disabled={update.isPending}>
              {update.isPending ? 'Saving…' : 'Save'}
            </button>
            <button type="button" className="button-secondary" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          {errors.pages_read ? (
            <p id={errorId('pages_read')} className="field-error">
              {errors.pages_read}
            </p>
          ) : null}
          {errors.log_date ? (
            <p id={errorId('log_date')} className="field-error">
              {errors.log_date}
              {takenId !== null && loadedIds.has(takenId) ? (
                <>
                  {' '}
                  <button type="button" className="link-button" onClick={() => focusRow(takenId)}>
                    Go to {formatDate(date)}
                  </button>
                </>
              ) : null}
            </p>
          ) : null}
          {server.summary ? (
            <p className="field-error" role="alert">
              {server.summary}
            </p>
          ) : null}
        </form>
      </li>
    );
  }

  return (
    <li id={rowId(log.id)} tabIndex={-1} className="log-row">
      <span className="log-row-date">{formatDate(log.log_date)}</span>
      <span className="log-row-pages">{pagesLabel}</span>
      <span className="log-row-actions">
        {/* aria-label rather than visually hidden text: accessible-name rules can drop
            the space before hidden text ("Editthe log…"). */}
        <button
          type="button"
          className="button-secondary"
          onClick={startEditing}
          aria-label={`Edit the log for ${formatDate(log.log_date)}`}
        >
          Edit
        </button>
        <button
          type="button"
          className="button-secondary"
          onClick={() => setConfirming(true)}
          aria-label={`Delete the log for ${formatDate(log.log_date)}`}
        >
          Delete
        </button>
      </span>
      <ConfirmDialog
        open={confirming}
        title={`Delete the log for ${formatDate(log.log_date)}?`}
        confirmLabel="Delete"
        busy={remove.isPending}
        onConfirm={confirmDelete}
        onCancel={() => setConfirming(false)}
      >
        <p>
          This removes {pagesLabel} from your reading history. Your shelf status doesn&apos;t
          change.
        </p>
        {remove.isError ? (
          <p className="field-error" role="alert">
            {formError(remove.error)}
          </p>
        ) : null}
      </ConfirmDialog>
    </li>
  );
}

interface ReadingLogListProps {
  bookId: number;
  onChanged: (message: string) => void;
}

/** This book's logs, newest first, with inline edit and confirmed delete. */
export function ReadingLogList({ bookId, onChanged }: ReadingLogListProps) {
  const logs = useBookLogs(bookId);
  const rows = logs.data?.pages.flatMap((page) => page.results) ?? [];
  const loadedIds = new Set(rows.map((log) => log.id));

  if (logs.isPending) return <p role="status">Loading your reading log…</p>;
  if (logs.isError) {
    return (
      <p className="error-summary" role="alert">
        {formError(logs.error)}
      </p>
    );
  }
  if (!rows.length) return <p className="hint">No pages logged for this book yet.</p>;

  return (
    <>
      <ul className="log-list" aria-label="Reading log">
        {rows.map((log) => (
          <LogRow key={log.id} log={log} loadedIds={loadedIds} onChanged={onChanged} />
        ))}
      </ul>
      {logs.hasNextPage ? (
        <button
          type="button"
          className="button-secondary more-results"
          onClick={() => void logs.fetchNextPage()}
          disabled={logs.isFetchingNextPage}
        >
          {logs.isFetchingNextPage ? 'Loading…' : 'Show older logs'}
        </button>
      ) : null}
    </>
  );
}
