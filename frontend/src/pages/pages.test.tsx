import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { ComparisonResponse, DocumentSummary } from "@/api/client";
import fixture from "@/test/fixtures/comparison.json";
import fixtureF1 from "@/test/fixtures/comparison_f1.json";
import fixtureV120 from "@/test/fixtures/comparison_v120.json";
import { mockFetch, renderAt } from "@/test/utils";

import { CompareBuilderPage } from "./CompareBuilderPage";
import { ComparisonPage } from "./ComparisonPage";
import { HistoryPage } from "./HistoryPage";
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

describe("CompareBuilderPage details and restore", () => {
  const prices = { version: "2026.1", source: "illustrative", prices: { imaging: 1000, specialist_visit: 250 }, labels: { imaging: "Imaging (CT/PET, MRI)", specialist_visit: "Specialist visit" } };
  const scenarios = { presets: [{ id: "low", label: "Low use", description: "", events: [] }], event_types: { mri: { label: "MRI" } } };
  const catalogSelection = () =>
    localStorage.setItem("plan-compare:selection", JSON.stringify([
      { documentId: "a", label: "Moda Bronze", source: "catalog", catalogPlanId: "17933TX0010006-00" },
      { documentId: "b", label: "My upload", source: "upload" },
    ]));

  it("fills catalog premiums from age and rating area, and keeps typed premiums", async () => {
    catalogSelection();
    const { calls } = mockFetch({
      "/meta/scenarios": scenarios,
      "/meta/reference-prices": prices,
      "/catalog/facets": { state: [], metal: [], plan_type: [], issuer: [], premiums_loaded: true },
      "/catalog/rating-areas": { state: "TX", items: [{ rating_area: "Rating Area 3", plans_priced: 67 }, { rating_area: "Rating Area 9", plans_priced: 40 }] },
      "/premiums": { items: [{ plan_id: "17933TX0010006-00", age: "40", rating_area: "Rating Area 3", monthly_premium: 553.37 }] },
      "/premium-quote": { plan_id: "17933TX0010006-00", rating_area: "Rating Area 3", members: [], monthly_total: 553.37, missing_ages: [] },
      "POST /comparisons": fixture,
    });
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare" });
    expect(await screen.findByText("Your details")).toBeInTheDocument();
    const premium = screen.getByLabelText("Monthly premium for Moda Bronze");
    await waitFor(() => expect(premium).toHaveValue("553.37"));
    expect(screen.getByText("CMS 2026 rate, before subsidy")).toBeInTheDocument();
    expect(screen.getByLabelText("Rating area for TX")).toHaveValue("Rating Area 3");
    const quote = calls.find((c) => c.url.includes("/premium-quote"))!;
    expect(quote.url).toContain("ages=40");

    await userEvent.clear(premium);
    await userEvent.type(premium, "400");
    await userEvent.clear(screen.getByLabelText("Your age"));
    await userEvent.type(screen.getByLabelText("Your age"), "60");
    await waitFor(() => expect(calls.some((c) => c.url.includes("ages=60"))).toBe(true));
    expect(premium).toHaveValue("400"); // typed premiums are never overwritten

    await userEvent.click(screen.getAllByRole("button", { name: /compare 2 plans/i })[0]);
    await waitFor(() => expect(screen.getByText("other page")).toBeInTheDocument());
    const body = JSON.parse(String(calls.find((c) => c.init?.method === "POST")!.init!.body));
    expect(body.profile).toEqual({ ages: [60], rating_areas: { TX: "Rating Area 3" } });
    expect(body.inputs.a.monthly_premium).toBe(400);
  });

  it("sends changed reference prices", async () => {
    localStorage.setItem("plan-compare:selection", JSON.stringify([
      { documentId: "a", label: "Plan A", source: "upload" },
      { documentId: "b", label: "Plan B", source: "upload" },
    ]));
    const { calls } = mockFetch({
      "/meta/scenarios": scenarios,
      "/meta/reference-prices": prices,
      "/catalog/facets": { state: [], metal: [], plan_type: [], issuer: [], premiums_loaded: false },
      "POST /comparisons": fixture,
    });
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare" });
    await userEvent.click(await screen.findByRole("button", { name: /prices used for estimates/i }));
    await userEvent.type(screen.getByLabelText("Price for Imaging (CT/PET, MRI)"), "1800");
    expect(screen.queryByText("Your details")).not.toBeInTheDocument(); // no catalog plans
    await userEvent.click(screen.getAllByRole("button", { name: /compare 2 plans/i })[0]);
    await waitFor(() => expect(screen.getByText("other page")).toBeInTheDocument());
    const body = JSON.parse(String(calls.find((c) => c.init?.method === "POST")!.init!.body));
    expect(body.reference_price_overrides).toEqual({ imaging: 1800 });
    expect(body.profile).toBeNull();
  });

  it("keeps restored premiums when CMS premiums are available", async () => {
    // browser check 2026-10-29: restored premiums were overwritten by CMS rates
    const quote = { plan_id: "x", rating_area: "Rating Area 3", members: [], monthly_total: 553.37, missing_ages: [] };
    mockFetch({
      "/comparisons/cmpf1": fixtureF1,
      "/meta/scenarios": scenarios,
      "/meta/reference-prices": prices,
      "/catalog/facets": { state: [], metal: [], plan_type: [], issuer: [], premiums_loaded: true },
      "/catalog/rating-areas": { state: "TX", items: [{ rating_area: "Rating Area 3", plans_priced: 67 }] },
      "/premiums": { items: [{ plan_id: "x", age: "40", rating_area: "Rating Area 3", monthly_premium: 553.37 }] },
      "/premium-quote": quote,
    });
    for (const cache of [{}, { '["comparison","cmpf1"]': fixtureF1 }]) {
      // second pass: the comparison is already cached, as when arriving from its result page
      localStorage.clear();
      const { unmount } = renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare?from=cmpf1", cache });
      const [a, b] = (fixtureF1 as unknown as ComparisonResponse).result.plans;
      const input = await screen.findByLabelText(`Monthly premium for ${a.plan_name}`);
      await screen.findByText("Your details");
      await waitFor(() => expect(screen.getByLabelText("Rating area for TX")).toHaveValue("Rating Area 3"));
      await new Promise((r) => setTimeout(r, 50));
      expect(input).toHaveValue("320");
      expect(screen.getByLabelText(`Monthly premium for ${b.plan_name}`)).toHaveValue("290");
      unmount();
    }
  });

  it("restores every input of a stored comparison", async () => {
    mockFetch({
      "/comparisons/cmpf1": fixtureF1,
      "/meta/scenarios": scenarios,
      "/meta/reference-prices": prices,
      "/catalog/facets": { state: [], metal: [], plan_type: [], issuer: [], premiums_loaded: false },
    });
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare?from=cmpf1" });
    const [a, b] = (fixtureF1 as unknown as ComparisonResponse).result.plans;
    expect(await screen.findByLabelText(`Monthly premium for ${a.plan_name}`)).toHaveValue("320");
    expect(screen.getByLabelText(`Monthly premium for ${b.plan_name}`)).toHaveValue("290");
  });
});

describe("ComparisonPage", () => {
  const data = fixture as unknown as ComparisonResponse;

  it("renders headline numbers, ranges and the explanation", async () => {
    mockFetch({ "/comparisons/cmp1": data });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmp1" });
    expect(await screen.findByText("What this means for you")).toBeInTheDocument();
    expect(screen.getByText("Numbers checked").closest("[title]")).toHaveAttribute("title", expect.stringContaining("statements about deductibles and coverage"));
    expect(screen.getAllByText("Plan A").length).toBeGreaterThan(0); // cards carry the letters the explanation uses
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

  it("shows before- and after-deductible costs and says when the verdict depends on the deductible", async () => {
    mockFetch({ "/comparisons/cmpf1": fixtureF1 });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmpf1" });
    const row = (await screen.findByRole("cell", { name: /^Specialist visit/ })).closest("tr")!;
    expect(within(row).getByText("Before deductible ≈ $250")).toBeInTheDocument();
    expect(within(row).getByText("After deductible ≈ $0")).toBeInTheDocument();
    const badge = within(row).getByText("depends on deductible");
    expect(badge).toHaveAttribute("title", expect.stringContaining("Before the deductible: A $120 vs B $250"));
    expect(within(row).queryByText("lower cost")).not.toBeInTheDocument();
    // the catastrophic plan's first primary care visits really are cheaper
    const pcp = screen.getByRole("cell", { name: /^Primary care visit/ }).closest("tr")!;
    expect(within(pcp).getByText("lower cost")).toBeInTheDocument();
  });

  it("renders comparisons stored by engine 1.2.0 as before", async () => {
    mockFetch({ "/comparisons/cmp1": fixtureV120 });
    renderAt(<ComparisonPage />, { path: "/comparisons/:id", route: "/comparisons/cmp1" });
    expect(await screen.findByText("Side by side")).toBeInTheDocument();
    expect(screen.queryByText(/Before deductible/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/per use$/).length).toBeGreaterThan(0);
    expect(screen.getByText(/assumes the deductible is already met/)).toBeInTheDocument();
  });
});

describe("Describe your year", () => {
  const scenarios = { presets: [{ id: "low", label: "Low use", description: "", events: [] }], event_types: { specialist_visit: { label: "Specialist visit" }, childbirth: { label: "Childbirth" } } };
  const routes = (intake: boolean) => ({
    "/meta/scenarios": scenarios,
    "/meta/reference-prices": { version: "v", source: "s", prices: {}, labels: {} },
    "/catalog/facets": { state: [], metal: [], plan_type: [], issuer: [], premiums_loaded: false },
    "/health": { status: "ok", version: "2", parser_version: "p", engine_version: "e", llm_mode: "fake", llm_configured: true, intake_available: intake, db: true },
    "POST /usage/interpret": {
      events: [{ event: "specialist_visit", count: 3, member: 0, quote: "3 specialist visits", basis: "3" }],
      unmodeled: [{ quote: "dental cleanings", reason: "adult dental isn't in the catalog" }],
      model: "fake",
    },
    "POST /comparisons": fixture,
  });
  const select = () =>
    localStorage.setItem("plan-compare:selection", JSON.stringify([
      { documentId: "a", label: "Plan A", source: "upload" },
      { documentId: "b", label: "Plan B", source: "upload" },
    ]));

  it("is hidden unless the server enables it", async () => {
    select();
    mockFetch(routes(false));
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare" });
    await screen.findByText("Low use");
    expect(screen.queryByText(/Describe your year/)).not.toBeInTheDocument();
  });

  it("needs the notice, then adds editable events and lists what isn't included", async () => {
    select();
    sessionStorage.clear();
    const { calls } = mockFetch(routes(true));
    renderAt(<CompareBuilderPage />, { path: "/compare", route: "/compare" });
    await userEvent.type(await screen.findByLabelText("Describe your expected care"), "3 specialist visits and dental cleanings");
    const go = screen.getByRole("button", { name: "Interpret" });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /sent to an AI service/ }));
    await userEvent.click(go);
    expect(await screen.findByText("from your description")).toBeInTheDocument();
    expect(screen.getByLabelText("Event")).toHaveValue("specialist_visit");
    expect(screen.getByLabelText("Times per year")).toHaveValue(3);
    expect(screen.getByText(/adult dental isn't in the catalog/)).toBeInTheDocument();
    const sent = JSON.parse(String(calls.find((c) => c.url.endsWith("/usage/interpret"))!.init!.body));
    expect(sent).toEqual({ text: "3 specialist visits and dental cleanings", coverage_tier: "individual", members: [] });
    // nothing is compared until the user presses Compare
    expect(calls.some((c) => c.url.endsWith("/comparisons"))).toBe(false);
    await userEvent.click(screen.getAllByRole("button", { name: /compare 2 plans/i })[0]);
    await waitFor(() => expect(screen.getByText("other page")).toBeInTheDocument());
    const body = JSON.parse(String(calls.find((c) => c.url.endsWith("/comparisons"))!.init!.body));
    expect(body.custom_scenario.events).toEqual([{ event: "specialist_visit", count: 3, member: 0 }]);
  });
});

describe("HistoryPage", () => {
  const items = [
    { id: "c1", created_at: new Date().toISOString(), plan_names: ["Moda Bronze", "Anthem Catastrophic"], scenario_labels: ["Low use", "Mine"] },
    { id: "c2", created_at: new Date().toISOString(), plan_names: ["Gold", "Silver"], scenario_labels: [] },
  ];

  it("lists saved comparisons and deletes one", async () => {
    const { calls } = mockFetch({ "/comparisons": items, "DELETE /comparisons/c1": [204, null] });
    renderAt(<HistoryPage />, { path: "/comparisons", route: "/comparisons" });
    expect(await screen.findByRole("link", { name: "Moda Bronze vs Anthem Catastrophic" })).toHaveAttribute("href", "/comparisons/c1");
    expect(screen.getByText(/Low use, Mine/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete comparison of Moda Bronze and Anthem Catastrophic" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE" && c.url.endsWith("/comparisons/c1"))).toBe(true));
  });

  it("asks before deleting everything", async () => {
    const { calls } = mockFetch({ "/comparisons": items, "DELETE /comparisons": [204, null] });
    renderAt(<HistoryPage />, { path: "/comparisons", route: "/comparisons" });
    await userEvent.click(await screen.findByRole("button", { name: "Delete all" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Delete all 2 saved comparisons?");
    expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Delete all" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE" && c.url.endsWith("/comparisons"))).toBe(true));
  });

  it("shows an empty state", async () => {
    mockFetch({ "/comparisons": [] });
    renderAt(<HistoryPage />, { path: "/comparisons", route: "/comparisons" });
    expect(await screen.findByText("No saved comparisons")).toBeInTheDocument();
  });
});
