import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  /** When this changes (the page's path), a crashed page gets another try. */
  resetKey?: string;
  /** Injected in tests; jsdom can't reload. */
  onReload?: () => void;
}

interface ErrorBoundaryState {
  error: Error | null;
  resetKey?: string;
}

/**
 * A page that throws while rendering shows "Something went wrong" with a Reload button
 * instead of a blank screen, and the error is logged to the console. React needs a class
 * component for this (there's no hook equivalent).
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: ErrorBoundaryState,
  ): Partial<ErrorBoundaryState> | null {
    // Navigating to another page clears the error.
    return props.resetKey !== state.resetKey ? { error: null, resetKey: props.resetKey } : null;
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Shelfwise: a page crashed.', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const reload = this.props.onReload ?? (() => window.location.reload());
    return (
      <section className="panel" role="alert" aria-labelledby="crash-title">
        <h1 id="crash-title">Something went wrong</h1>
        <p>This page hit an error. Reloading usually fixes it.</p>
        <button type="button" onClick={reload}>
          Reload
        </button>
      </section>
    );
  }
}
