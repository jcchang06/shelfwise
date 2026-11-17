import type { ReactNode } from 'react';

import { CHOOSABLE_DNF_REASONS, DNF_REASON_LABELS, type DnfReason } from '../../api/types';
import { FieldLabel } from '../forms/FieldLabel';
import type { DnfValues } from './dnfValues';

interface DnfFieldsProps {
  idPrefix: string;
  values: DnfValues;
  onChange: (values: DnfValues) => void;
  errors: Record<string, string | undefined>;
  today: string;
  pageCount: number | null;
  disabled?: boolean;
}

/** Reason, stopped-at page, stopped-on date and note, used wherever a book becomes DNF. */
export function DnfFields({
  idPrefix,
  values,
  onChange,
  errors,
  today,
  pageCount,
  disabled,
}: DnfFieldsProps) {
  const set = (patch: Partial<DnfValues>) => onChange({ ...values, ...patch });
  const invalid = (field: string) => (errors[field] ? true : undefined);
  const describedBy = (field: string) => (errors[field] ? `${idPrefix}-${field}-error` : undefined);
  const fieldError = (field: string): ReactNode =>
    errors[field] ? (
      <p id={`${idPrefix}-${field}-error`} className="field-error">
        {errors[field]}
      </p>
    ) : null;

  return (
    <>
      <div className="form-field">
        <FieldLabel htmlFor={`${idPrefix}-reason`} need="optional">
          Why did you stop?
        </FieldLabel>
        <select
          id={`${idPrefix}-reason`}
          value={values.reason}
          onChange={(event) => set({ reason: event.target.value as DnfReason | '' })}
          aria-invalid={invalid('dnf_reason')}
          aria-describedby={describedBy('dnf_reason')}
          disabled={disabled}
        >
          <option value="">{DNF_REASON_LABELS.not_specified}</option>
          {CHOOSABLE_DNF_REASONS.map((value) => (
            <option key={value} value={value}>
              {DNF_REASON_LABELS[value]}
            </option>
          ))}
        </select>
        {fieldError('dnf_reason')}
      </div>
      <div className="form-field">
        <FieldLabel htmlFor={`${idPrefix}-page`} need="optional">
          Stopped at page
        </FieldLabel>
        <input
          id={`${idPrefix}-page`}
          type="number"
          inputMode="numeric"
          min={0}
          max={pageCount ?? undefined}
          value={values.page}
          onChange={(event) => set({ page: event.target.value })}
          aria-invalid={invalid('dnf_page')}
          aria-describedby={describedBy('dnf_page')}
          disabled={disabled}
        />
        {fieldError('dnf_page')}
      </div>
      <div className="form-field">
        <FieldLabel htmlFor={`${idPrefix}-dnf_at`} need="optional">
          Stopped on
        </FieldLabel>
        <input
          id={`${idPrefix}-dnf_at`}
          type="date"
          value={values.at}
          max={today}
          onChange={(event) => set({ at: event.target.value })}
          aria-invalid={invalid('dnf_at')}
          aria-describedby={describedBy('dnf_at')}
          disabled={disabled}
        />
        {fieldError('dnf_at')}
      </div>
      <div className="form-field">
        <FieldLabel htmlFor={`${idPrefix}-note`} need="optional">
          Note
        </FieldLabel>
        <textarea
          id={`${idPrefix}-note`}
          rows={2}
          value={values.note}
          onChange={(event) => set({ note: event.target.value })}
          disabled={disabled}
        />
      </div>
    </>
  );
}
