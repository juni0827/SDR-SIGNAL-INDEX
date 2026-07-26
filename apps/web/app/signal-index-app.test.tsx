import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SignalIndexApp } from "./signal-index-app";

vi.mock("next/navigation", () => ({useRouter: () => ({push: vi.fn()})}));
vi.mock("echarts", () => ({init: () => ({setOption: vi.fn(), dispose: vi.fn()})}));
afterEach(cleanup);

function renderApp(path: string) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  return render(<QueryClientProvider client={client}><SignalIndexApp initialPath={path}/></QueryClientProvider>);
}

describe("Signal Index UI", () => {
  it("renders accessible responsive navigation", () => {
    renderApp("/dashboard");
    expect(screen.getByRole("navigation", {name: "Primary navigation"})).toBeInTheDocument();
    expect(screen.getByTestId("main-content")).toBeInTheDocument();
    expect(screen.getByRole("navigation", {name: "Mobile navigation"})).toBeInTheDocument();
  });

  it("opens the command palette", () => {
    renderApp("/dashboard");
    fireEvent.click(screen.getByTestId("command-trigger"));
    expect(screen.getByRole("dialog", {name: "Command palette"})).toBeInTheDocument();
  });

  it("supports transcript correction without replacing the machine candidate", () => {
    renderApp("/segments/demo");
    const editor = screen.getByTestId("transcript-editor");
    fireEvent.change(editor, {target: {value: "Corrected evidence text"}});
    expect(editor).toHaveValue("Corrected evidence text");
  });

  it("exposes a structured session search and reproducible query JSON", () => {
    renderApp("/sessions");
    fireEvent.change(screen.getByTestId("session-search"), {target: {value: "KILO 72"}});
    expect(screen.getByText(/"text":"KILO 72"/)).toBeInTheDocument();
    expect(screen.getByTestId("session-table")).toBeInTheDocument();
  });

  it("renders graph filters and an evidence inspector", () => {
    renderApp("/graph");
    expect(screen.getByLabelText("Min confidence")).toBeInTheDocument();
    expect(screen.getByText("Causal claim")).toBeInTheDocument();
    expect(screen.getByText("Time order is not treated as causation.")).toBeInTheDocument();
  });

  it("provides the universal offline-capable inbox form", () => {
    renderApp("/inbox");
    expect(screen.getByTestId("inbox-form")).toBeInTheDocument();
    expect(screen.getByText("Capture now, classify later")).toBeInTheDocument();
  });
});
