import { useId, useState, type FormEvent } from 'react';

import { fieldErrors, formError } from '../../api/errors';
import { MAX_IMPORT_BYTES, type GoodreadsImport } from '../../api/imports';
import { useUploadImport } from '../../hooks/useImports';

interface UploadFormProps {
  onUploaded: (created: GoodreadsImport) => void;
}

/** Pick a Goodreads export CSV and upload it. Basic checks happen before sending. */
export function UploadForm({ onUploaded }: UploadFormProps) {
  const id = useId();
  const upload = useUploadImport();
  const [file, setFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);

  const serverError = upload.error
    ? (fieldErrors(upload.error).file ?? formError(upload.error))
    : null;
  const error = clientError ?? serverError;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setClientError('Choose your Goodreads export (a .csv file).');
      return;
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setClientError('That isn’t a .csv file. Goodreads exports a file ending in .csv.');
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setClientError('That file is too large. The limit is 5 MB.');
      return;
    }
    setClientError(null);
    upload
      .mutateAsync(file)
      .then(onUploaded)
      .catch(() => undefined); // shown from upload.error
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>Import from Goodreads</h2>
      <p>
        In Goodreads, go to <strong>My Books → Import and export → Export Library</strong>, then
        upload the CSV file here. Your shelves, ratings, dates and reviews come across; books you
        import again are updated, never duplicated.
      </p>
      <p className="hint">
        The file is read once and never stored. Only the columns Shelfwise uses are kept, until the
        import finishes.
      </p>
      <div className="form-field">
        <label htmlFor={`${id}-file`}>Goodreads export (CSV)</label>
        <input
          id={`${id}-file`}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null);
            setClientError(null);
            upload.reset();
          }}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
        />
        {error ? (
          <p id={`${id}-error`} className="field-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
      <button type="submit" disabled={upload.isPending}>
        {upload.isPending ? 'Uploading…' : 'Start import'}
      </button>
    </form>
  );
}
