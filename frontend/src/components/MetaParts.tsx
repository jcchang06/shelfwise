import { Fragment, type ReactNode } from 'react';

/** Parts of a meta line ("Author · 2019 · 320 pages"), skipping empty ones. */
export function MetaParts({ parts }: { parts: ReactNode[] }) {
  const shown = parts.filter((part) => part !== null && part !== false && part !== '');
  return (
    <>
      {shown.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? ' · ' : null}
          {part}
        </Fragment>
      ))}
    </>
  );
}
