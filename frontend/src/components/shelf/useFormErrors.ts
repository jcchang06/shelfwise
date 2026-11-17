import { fieldErrors, formError, type FieldErrors } from '../../api/errors';

/** Field errors plus a summary for anything the fields don't explain. */
export function describeError(
  error: unknown,
  fields: readonly string[],
): { fields: FieldErrors; summary: string | null } {
  if (!error) return { fields: {}, summary: null };
  const byField = fieldErrors(error);
  const shown: FieldErrors = {};
  const other: string[] = [];
  for (const [field, message] of Object.entries(byField)) {
    if (fields.includes(field)) shown[field] = message;
    else other.push(message);
  }
  const summary = formError(error) ?? (other.length ? other.join(' ') : null);
  return { fields: shown, summary };
}
