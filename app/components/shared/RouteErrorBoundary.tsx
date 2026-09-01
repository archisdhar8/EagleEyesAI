"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { route: string; children: ReactNode };
type State = { error: boolean };

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: false };

  static getDerivedStateFromError(): State {
    return { error: true };
  }

  componentDidCatch(_error: Error, info: ErrorInfo) {
    const telemetry = { route: this.props.route, component_stack_lines: info.componentStack?.split("\n").filter(Boolean).length || 0 };
    console.error("[eagleeyes:route-error]", telemetry);
    window.dispatchEvent(new CustomEvent("eagleeyes:route-error", { detail: telemetry }));
  }

  componentDidUpdate(previous: Props) {
    if (previous.route !== this.props.route && this.state.error) this.setState({ error: false });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return <section className="workspace panel route-error-state" role="alert">
      <span>Section unavailable</span>
      <h2>This section could not load.</h2>
      <p>Your navigation and saved data are still available. Retry this section when ready.</p>
      <button className="primary" onClick={() => this.setState({ error: false })}>Retry section</button>
    </section>;
  }
}
