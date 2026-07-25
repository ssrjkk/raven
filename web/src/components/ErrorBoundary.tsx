import { Component, type ErrorInfo,type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-4">
        <div className="text-4xl">РІС™В </div>
        <h2 className="text-lg font-semibold text-primary">
          Something went wrong
        </h2>
        <pre className="text-sm max-w-lg text-center whitespace-pre-wrap text-tertiary">
          {this.state.error.message}
        </pre>
        <button
          onClick={() => this.setState({ error: null })}
          className="px-4 py-2 rounded-lg text-sm font-medium transition bg-accent text-white"
        >
          Try again
        </button>
      </div>
    );
  }
}
