import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * After a failed Save, move focus to the first field marked aria-invalid (T-7), whether
 * the browser-side check or the API found the problem. Call focusInvalid() each time;
 * focus moves after React has rendered the errors.
 */
export function useFocusInvalid<T extends HTMLElement = HTMLFormElement>() {
  const ref = useRef<T>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (attempt) ref.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [attempt]);
  const focusInvalid = useCallback(() => setAttempt((n) => n + 1), []);
  return { ref, focusInvalid };
}
