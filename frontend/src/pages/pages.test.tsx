import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ComparisonResponse, DocumentSummary } from "@/api/client";
import fixture from "@/test/fixtures/comparison.json";
import { mockFetch, renderAt } from "@/test/utils";

import { CompareBuilderPage } from "./CompareBuilderPage";
import { ComparisonPage } from "./ComparisonPage";
import { PlansPage } from "./PlansPage";

const doc = (over: Partial<DocumentSummary>): DocumentSummary => ({
  id: "d1", filename: "gold.pdf", source: "upload", status: "ready", plan_name: "Core Gold 1500", issuer: "PacificSource",
  plan_type: "EPO", npages: 7, doc_confidence: 0.95, summaries_status: "ready", warning_count: 0, created_at: new Date().toISOString(),
  error_code: null, error_message: null, catalog_plan_id: null, ...over,
});

beforeEach(() => localStorage.clear());

describe("PlansPage", () => {
  it("shows the empty state", async () => {
    mockFetch({ "/documents": { items: [] }, "/health": { status: "ok" } });
    renderAt(<PlansPage />);
    expect(await screen.findByText("No plans yet")).toBeInTheDocument();
  });

  it("lists plans with status and lets ready plans be selected", async () => {
    mockFetch({
      "/documents": { items: [doc({}), doc({ id: "d2", status: "extracting", plan_name: null, filename: "new.pdf" }), doc({ id: "d3", status: "failed", plan_name: null, filename: "scan.pdf", error_message: "The PDF has no text layer" })] },
    });
    renderAt(<PlansPage />);
    expect(await screen.findByText("Core Gold 1500")).toBeInTheDocument();
    expect(screen.getByText("Reading PDF")).toBeInTheDocument();
    expect(screen.getByText("The PDF has no text layer")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Uploaded plans" });
    const buttons = within(list).getAllByRole("button", { name: /compare/i });
    expect(buttons[1]).toBeDisabled(); // still extracting
    await userEvent.click(buttons[0]);
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("shows an error state when the API fails", async () => {
    mockFetch({ "/documents": [500, { error: { code: "E_INTERNAL", message: "Internal server error", details: {} } }] });
    renderAt(<PlansPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Internal server error");
  });
});

describe("CompareBuilderPage", () => {
  it("asks for plans when fewer than two are selected", () => {
    mockFetch({ "/meta/scenarios": { presets: [], event_types: {} } });
    renderAt(<CompareBuilderPage />);
    expect(screen.getByText("Pick at least two plans")).toBeInTheDocument();
  });

  it("validates premiums and submits a comparison", async () => {
    localStorage.setItem("plan-compare:selection", JSON.stringify([
      { documentId: "a", label: "Plan A", source: "upload" },
      { documentId: "b", label: "Plan B", source: "upload" },
    ]));
    const { calls } = mockFetch({
      "/meta/scenarios": { presets: [{ id: "low", label: "Low use", description: "", events: [] }], event_types: { mri: { label: "MRI" } } },
      "POST /comparisons": fixture,
    });
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare" });
    await screen.findByText("Low use");
    const premium = screen.getByLabelText("Monthly premium for Plan A");
    await userEvent.type(premium, "abc");
    await userEvent.click(screen.getAllByRole("button", { name: /compare 2 plans/i })[0]);
    expect(await screen.findByText(/Enter an amount like 450/)).toBeInTheDocument();
    await userEvent.clear(premium);
    await userEvent.type(premium, "500");
    await userEvent.click(screen.getAllByRole("button", { name: /compare 2 plans/i })[0]);
    await waitFor(() => expect(screen.getByText("other page")).toBeInTheDocument());
    const body = JSON.parse(String(calls.find((c) => c.init?.method === "POST")!.init!.body));
    expect(body.inputs.a.monthly_premium).toBe(500);
    expect(body.document_ids).toEqual(["a", "b"]);
  });
});

describe("ComparisonPage", () => {
  const data = fixture as unknown as ComparisonResponse;

  it("renders headline numbers, ranges and the explanation", async () => {
    mockFetch({ "/comparisons/cmp1": data });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmp1" });
    expect(await screen.findByText("What this means for you")).toBeInTheDocument();
    expect(screen.getByText("Numbers verified")).toBeInTheDocument();
    expect(screen.getByText(data.explanation!.content.headline)).toBeInTheDocument();
    expect(screen.getAllByText("$6,848 – $7,840").length).toBeGreaterThan(0); // worked example, plan A moderate
    expect(screen.getAllByText("$7,310").length).toBeGreaterThan(0);
    expect(screen.getByText(/Ranges overlap/)).toBeInTheDocument();
  });

  it("shows a loading state while the explanation is written", async () => {
    mockFetch({ "/comparisons/cmp1": { ...data, explanation_status: "running", explanation: null } });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmp1" });
    expect(await screen.findByLabelText("Writing the explanation")).toBeInTheDocument();
  });

  it("explains a failed explanation without hiding the numbers", async () => {
    mockFetch({ "/comparisons/cmp1": { ...data, explanation_status: "failed", explanation: null } });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmp1" });
    expect(await screen.findByText(/couldn't be written/)).toBeInTheDocument();
    expect(screen.getByText("Side by side")).toBeInTheDocument();
  });
});
