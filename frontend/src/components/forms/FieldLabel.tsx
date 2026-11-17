import type { ReactNode } from 'react';

export type FieldNeed = 'required' | 'optional';

/**
 * A field label ending in "(required)" or "(optional)" (T-7). The word is part of the
 * label, so screen readers hear it, and nothing relies on an asterisk or on color.
 */
export function FieldLabel({
  htmlFor,
  need,
  className,
  children,
}: {
  htmlFor: string;
  need?: FieldNeed;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className={className}>
      {children}
      {need ? (
        <>
          {/* The space sits outside the span: some name calculations drop it inside. */}{' '}
          <span className="field-need">({need})</span>
        </>
      ) : null}
    </label>
  );
}
