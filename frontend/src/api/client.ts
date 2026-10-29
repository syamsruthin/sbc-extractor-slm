import type { components } from "./schema";

export type S = components["schemas"];
export type DocumentSummary = S["DocumentSummary"];
export type DocumentDetail = S["DocumentDetail"];
export type BenefitsDocument = S["BenefitsDocument"];
export type CatalogPlan = S["CatalogPlan"];
export type CatalogPage = S["CatalogPage"];
export type CatalogFacets = S["CatalogFacets"];
export type ComparisonRequest = S["ComparisonRequest"];
export type ComparisonResponse = S["ComparisonResponse"];
export type ComparisonResult = S["ComparisonResult"];
export type ScenarioCatalog = S["ScenarioCatalog"];
export type ReferencePrices = S["ReferencePrices"];
export type Provenance = S["Provenance"];
export type Health = S["Health"];
export type Money = S["Money"];
export type CostShare = S["CostShare"];
export type PremiumQuotes = S["PremiumQuotes"];
export type RatingAreas = S["RatingAreas"];
export type HouseholdQuote = S["HouseholdQuote"];
export type InterpretUsageRequest = S["InterpretUsageRequest"];
export type InterpretUsageResponse = S["InterpretUsageResponse"];

/** Error envelope from the API: {"error": {code, message, details}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "E_NETWORK", "Can't reach the server. Is the backend running?");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error;
    throw new ApiError(res.status, e?.code ?? "E_HTTP", e?.message ?? `Request failed (${res.status})`, e?.details ?? {});
  }
  return body as T;
}

const json = (method: string, data?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: data === undefined ? undefined : JSON.stringify(data),
});

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  listDocuments: () => request<S["DocumentList"]>("/documents"),
  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  uploadDocument: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<DocumentSummary>("/documents", { method: "POST", body: fd });
  },
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  reprocessDocument: (id: string) => request<DocumentSummary>(`/documents/${id}/reprocess`, { method: "POST" }),
  generateSummaries: (id: string) => request<DocumentSummary>(`/documents/${id}/summaries`, { method: "POST" }),
  provenance: (id: string, path: string) => request<Provenance>(`/documents/${id}/provenance${qs({ path })}`),
  pdfUrl: (id: string) => `${BASE}/documents/${id}/pdf`,
  searchCatalog: (p: { state?: string; metal?: string; plan_type?: string; issuer?: string; q?: string; sort?: string; offset?: number; limit?: number }) =>
    request<CatalogPage>(`/catalog/plans${qs(p)}`),
  facets: () => request<CatalogFacets>("/catalog/facets"),
  premiums: (planId: string, age: string) => request<PremiumQuotes>(`/catalog/plans/${planId}/premiums${qs({ age })}`),
  ratingAreas: (state: string) => request<RatingAreas>(`/catalog/rating-areas${qs({ state })}`),
  premiumQuote: (planId: string, ratingArea: string, ages: number[]) =>
    request<HouseholdQuote>(`/catalog/plans/${planId}/premium-quote${qs({ rating_area: ratingArea, ages: ages.join(",") })}`),
  scenarios: () => request<ScenarioCatalog>("/meta/scenarios"),
  referencePrices: () => request<ReferencePrices>("/meta/reference-prices"),
  createComparison: (req: ComparisonRequest) => request<ComparisonResponse>("/comparisons", json("POST", req)),
  getComparison: (id: string) => request<ComparisonResponse>(`/comparisons/${id}`),
  listComparisons: () => request<S["ComparisonListItem"][]>("/comparisons"),
  deleteComparison: (id: string) => request<void>(`/comparisons/${id}`, { method: "DELETE" }),
  deleteAllComparisons: () => request<void>("/comparisons", { method: "DELETE" }),
  interpretUsage: (req: InterpretUsageRequest) => request<InterpretUsageResponse>("/usage/interpret", json("POST", req)),
  regenerateExplanation: (id: string) => request<ComparisonResponse>(`/comparisons/${id}/explanation`, { method: "POST" }),
};
