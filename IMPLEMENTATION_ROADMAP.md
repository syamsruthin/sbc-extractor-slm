# Implementation Roadmap: SBC Plan Comparison v2

**Branch:** `design/v2-hybrid-pipeline` · **Started:** 2026-10-27 · **Design:** [docs/design/v2/](docs/design/v2/README.md)

## Solution in one paragraph

A user uploads health plan SBC PDFs (or picks plans from the marketplace catalog). A
deterministic Python parser extracts a standardized benefits JSON from each one. It is
anchored on the federally mandated SBC template. A capable LLM on OpenRouter re-reads only
the cells the parser is unsure about, and writes a short plain-language summary per benefit
section. A deterministic engine compares the plans and calculates money differences: per
service, per usage scenario, best and worst case. An LLM then turns that computed comparison
into an explanation. Every LLM output passes a numeric grounding check, and every LLM step
has a non-LLM fallback.

## Scope

**In scope:** PDF upload and validation · deterministic extraction with provenance and
confidence · cell-level LLM fallback · section summaries · plan catalog (1,829 local
marketplace SBCs + CMS PUF metadata + premiums when available) · cost engine and comparison
of 2–5 plans · grounded explanation · FastAPI backend · React frontend · automated tests ·
local run instructions.

**Deferred** (explicitly out of this roadmap): OCR for scanned PDFs, a PDF bounding-box
viewer (provenance shows page + source text instead), coverage-example parsing, auth/multi-user,
Postgres/Redis/job queue, SLM fine-tuning, production deployment.

## Assumptions

- Uploaded documents use the CMS SBC template (marketplace and employer plans both do).
- OpenRouter is the only LLM provider (`OPENROUTER_API_KEY`). The app must still work without it, in degraded mode.
- Premiums aren't in SBCs. Users enter them. Catalog premiums come from the CMS Rate PUF when it's loaded.
- Reference allowed amounts are illustrative estimates that users can override.
- Single-user local app. SQLite and local disk are enough.

## Dependencies

| Dependency | Version / source | Used for |
|---|---|---|
| Python + uv | 3.13 / uv | backend |
| FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, uvicorn | PyPI | API, models, config, DB |
| pdfplumber, pymupdf4llm | PyPI | PDF tables/words, markdown |
| httpx | PyPI | OpenRouter client |
| Jinja2, PyYAML | PyPI | templates, config |
| pytest, hypothesis, ruff, mypy | PyPI | tests, lint |
| Node + npm | 20 / 10 | frontend |
| React 18, Vite, TypeScript, Tailwind, TanStack Query, React Router, Recharts, react-hook-form, zod, sonner | npm | UI |
| Vitest, Testing Library, Playwright, openapi-typescript | npm | UI tests, typed API client |
| Existing data | `data/raw/sbc_pdfs` (1,829), `data/gold`, `data/labels/v1.4`, `data/manifest.csv`, `data/raw/puf/` | catalog, tests |

## Reused assets

| Asset | Reuse |
|---|---|
| `audit_tools/ext.py`, `mk.py`, `excl.py`, `mdclean.py`, `tables.py`, `gen.py` | Ported into `backend/sbcx/domain/parse/` (rules kept, hardcoded `~/audit` paths removed) |
| `src/schema.py` | Copied to `backend/sbcx/domain/sbc.py`; a drift test keeps them identical |
| `src/label_sbcs.py` | OpenRouter structured-output pattern (`strict_schema`, retries, budget) |
| `eval/score.py` | Scores parser output unchanged |
| `data/gold`, `data/labels/v1.4` | Acceptance and regression sets |
| `docs/design/v2/` | PRD, HLD, LLD, cost model (updated to match these decisions) |

## Key technical decisions

| Decision | Choice | Why |
|---|---|---|
| Extraction | Deterministic, template-anchored parser; LLM only for low-confidence cells | Fixed template; fast, exact, auditable |
| LLM provider | OpenRouter for fallback, summaries, explanation; model per task in env | User decision; one integration |
| Money math | Deterministic engine; LLM never computes | Arithmetic must be exact |
| Backend | FastAPI, layered `api → services → domain ← infra` | Requirement; testable pure domain |
| Jobs | FastAPI BackgroundTasks + status polling | Enough for a local single-user app |
| Storage | SQLite (SQLAlchemy 2) + local files under `backend/var/` | Zero setup; Postgres-ready ORM |
| Frontend | React + TypeScript + Vite + Tailwind + TanStack Query | Multi-screen app with uploads, polling, forms, charts; a typed client generated from OpenAPI |
| Contract | OpenAPI → `openapi-typescript` | One source of truth for request/response types |

## Status

| # | Milestone | Status | Notes |
|---|---|---|---|
| M0 | Roadmap + design-doc updates | ✅ Done | |
| M1 | Backend scaffold | ✅ Done | 6 tests, ruff + mypy clean |
| M2 | Domain models | ✅ Done | drift test vs src/schema.py |
| M3 | Layout layer | ✅ Done | markdown repair byte-identical to prototype on 40/40 docs |
| M4 | Cell rules | ✅ Done | 326 cell tests (300 mined from reviewed v1.4); added visit-sequence later-charge rule |
| M5 | Document parser | ✅ Done | gold 96.9–97.0% / 2.4% halluc; v1.4 reviewed 98.7% agreement |
| M6 | Provenance, validation, confidence | ✅ Done | τ = 0.75 from calibration |
| M7 | LLM infrastructure | ✅ Done | |
| M8 | Cell-level fallback | ⚠️ Done with deviation | gold target 98% not reached; see log |
| M9 | Persistence | ✅ Done | |
| M10 | Documents API | ✅ Done | |
| M11 | Catalog | ✅ Done | 1,829/1,829 plans ingested (30 states); 226,950 Rate PUF premium rows |
| M12 | Section summaries | ✅ Done | live: 39/39 summaries grounded on first try |
| M13 | Cost engine | ✅ Done | worked example reproduced exactly; hypothesis invariants |
| M14 | Comparison engine + API | ✅ Done | deterministic result hash |
| M15 | Explanation | ✅ Done | live: 3/3 explanations grounded, 0 policy violations |
| M16 | Frontend scaffold | ✅ Done | typed client generated from OpenAPI |
| M17 | My Plans + Plan Detail | ✅ Done | verified in the browser with real SBCs |
| M18 | Catalog screen | ✅ Done | |
| M19 | Compare Builder + Result | ✅ Done | live 3-plan comparison with grounded AI explanation |
| M20 | Integration + E2E | ✅ Done | Playwright green with fake LLM and with LLM off; API types check |
| M21 | Run readiness | ✅ Done | Docker verified 2026-10-28 (compose fix for Compose < 2.24) |

Legend: ⬜ not started · 🟡 in progress · ✅ done · ⚠️ done with deviation · ⏸ deferred

---

## Phase A: Setup and architecture

### M0 Roadmap and design alignment
- **Objective:** Record the plan, and update the design docs for the latest decisions (OpenRouter for every LLM step, catalog in scope, React frontend, fine-tuning deferred).
- **Tasks:** write this file; update `docs/design/v2/README.md`, `01-PRD.md` §9, `02-architecture.md` LLM table, `09-decisions.md` ADR-009/010.
- **Deliverables:** `IMPLEMENTATION_ROADMAP.md`, updated docs.
- **Dependencies:** none.
- **Acceptance:** every milestone has objective, tasks, deliverables, dependencies, acceptance and validation; docs don't contradict the roadmap.
- **Validation:** review.

### M1 Backend scaffold
- **Objective:** A runnable, linted, tested FastAPI skeleton with config, logging and error handling.
- **Tasks:**
  1. `backend/pyproject.toml` (uv project, deps above, ruff + mypy + pytest config).
  2. `sbcx/config.py`: `Settings` (pydantic-settings, `SBCX_` prefix, reads `backend/.env` and the repo `.env` for `OPENROUTER_API_KEY`): paths, DB URL, models per task, thresholds, budget.
  3. `sbcx/logging.py`: JSON log formatter, request-ID middleware (`X-Request-ID`).
  4. `sbcx/errors.py`: `AppError(code, message, status, details)` + handlers producing `{"error": {...}}`, including for validation errors and unhandled exceptions.
  5. `sbcx/main.py`: `create_app()`, CORS for the Vite dev origin, routers under `/api/v1`.
  6. `GET /api/v1/health` → `{status, version, llm_configured, db}`.
  7. Root `Makefile`: `backend-setup`, `backend-test`, `backend-lint`, `backend-dev`.
- **Deliverables:** `backend/` skeleton, tests `tests/unit/test_health.py`, `test_errors.py`.
- **Dependencies:** M0.
- **Acceptance:** `make backend-test` green; `make backend-lint` (ruff + mypy) green; health returns 200; an unknown route returns the error envelope.
- **Validation:** pytest with `TestClient`; curl to the running server.

### M2 Domain models and API schemas
- **Objective:** Typed contracts for every boundary.
- **Tasks:**
  1. `domain/sbc.py`: copy of `src/schema.py` models + `normalize`.
  2. `domain/benefits.py`: `BenefitsDocument`, `BenefitsExtras`, `FieldMeta`, `Warning`, `SectionSummary`, `Source`, `DeductibleType`.
  3. `domain/comparison.py`: `PlanInputs`, `Event`, `Scenario`, `Money`, `ServiceDiff`, `DrugTierDiff`, `ScenarioResult`, `ComparisonResult`, …
  4. `domain/explanation.py`: `Explanation`, `GroundingReport`.
  5. `api/schemas.py`: request/response DTOs (document summary, catalog plan, comparison request, paginated list).
- **Deliverables:** models + `tests/unit/test_schema_drift.py` (JSON schema of `domain/sbc.SBCExtraction` == `src/schema.SBCExtraction`).
- **Dependencies:** M1.
- **Acceptance:** drift test passes; `app.openapi()` builds with no errors.
- **Validation:** pytest.

## Phase B: Extraction (backend domain)

### M3 Layout layer
- **Objective:** Turn a PDF into a cached `LayoutDoc` with two views: pdfplumber tables/text/words and a cleaned pymupdf4llm markdown.
- **Tasks:**
  1. `parse/pdf_guard.py`: magic bytes, size ≤ 10 MB, pages ≤ 20, encryption, text layer → `AppError` codes `E_NOT_PDF`, `E_TOO_LARGE`, `E_ENCRYPTED`, `E_NO_TEXT_LAYER`.
  2. `parse/layout.py`: tables (first 12 pages), page text, words (for the exclusions box), markdown, `npages`.
  3. Port the `mdclean.py` repair (strip `~~`/`<mark>`, split run-together tokens using PDF word bigrams).
  4. JSON cache keyed by sha256 under `var/cache/layout/`.
  5. CLI `sbcx layout --all` to warm the cache for the corpus.
- **Deliverables:** modules + tests with gold PDFs and synthetic bad PDFs.
- **Dependencies:** M1.
- **Acceptance:** all 1,829 PDFs produce a layout without exceptions; guard tests cover every code.
- **Validation:** pytest; corpus run report (count, failures, mean seconds per doc).

### M4 Cell rules
- **Objective:** Port the price-cell parser with traceable rules.
- **Tasks:**
  1. `parse/textnorm.py`: `norm`, `dejunk` from `ext.py`.
  2. `parse/cells.py`: `parse_cost`, `ded_flag`, `PRICE`, not-covered rules; return `CellParse(cost, extra_note, rule_trace)`.
  3. Mine test cases: v1.4 reviewed cells joined with the parsed raw cell text (where unambiguous), plus hand-written convention cases (later charge, combined charge, zero rules, NC, flags).
- **Deliverables:** modules + `tests/cases/cells.jsonl` + `tests/unit/test_cells.py`.
- **Dependencies:** M2.
- **Acceptance:** ≥ 200 cell cases, all passing.
- **Validation:** pytest.

### M5 Document parser
- **Objective:** `extract(pdf) → SBCExtraction` equal in quality to the prototype that produced v1.4.
- **Tasks:**
  1. `parse/anchors.py`: row walk (`ext.extract`), header-row merge, packed rows, continuations, drug mode.
  2. `parse/columns.py`: `colkinds`, `pick` (IHCP, tiers, OON).
  3. `parse/drugs.py`: tier rows, `cat`, `split_names`.
  4. `parse/header.py`, `parse/questions.py`: plan info, deductible, OOP, referral, before-deductible list (`mk.build`).
  5. `parse/exclusions.py`: "Does NOT Cover" box column-major (`excl.py`).
  6. `parse/pipeline.py`: md view first, pdf-table view when ≥ 3 services are missing (as `gen.py` does); `clean()` + `normalize()`.
  7. CLI `sbcx extract <pdf>`, `sbcx score --set gold|v14` (writes `eval/predictions/parser_v2/…` and runs `eval/score.py`).
- **Deliverables:** modules, CLI, score reports in this file.
- **Dependencies:** M3, M4.
- **Acceptance:** gold parser-only ≥ 96% field accuracy and ≤ 3% hallucination; ≥ 95% field agreement on the 450 v1.4 reviewed docs; 0 crashes on the corpus. If a target is missed, record the number and the cause here before continuing.
- **Validation:** `eval/score.py` reports; regression test on 3 gold docs (exact JSON snapshot).

### M6 Provenance, validation, confidence
- **Objective:** Every field carries where it came from and how sure we are.
- **Tasks:** `extract/assemble.py` (page + raw text + rule trace per leaf; limitations text per service; `deductible_type`); `extract/rules.py` (warnings W_*); `extract/confidence.py` (penalty factors); build a `BenefitsDocument`.
- **Deliverables:** modules + tests.
- **Dependencies:** M5.
- **Acceptance:** every non-null leaf in `benefits` has a provenance entry; on v1.4 reviewed, accuracy is non-decreasing across confidence buckets; threshold τ chosen and recorded.
- **Validation:** pytest + calibration table recorded here.

### M7 LLM infrastructure
- **Objective:** One safe OpenRouter client.
- **Tasks:** `infra/llm/base.py` (`LLMClient` protocol, `LLMResult`); `openrouter.py` (httpx, `json_schema` strict response format via `strict_schema`, retries with backoff, timeout, budget cap, usage → cost); `cache.py` (sqlite/json cache by request hash); `fake.py` (scripted responses); call log.
- **Deliverables:** modules + tests.
- **Dependencies:** M1, M2.
- **Acceptance:** fake-client tests cover success, invalid JSON, timeout/retry, budget exhausted; one `@pytest.mark.live` smoke test passes when a key is present.
- **Validation:** `pytest -m "not live"` in CI; `pytest -m live` once manually.

### M8 Cell-level fallback
- **Objective:** Fix low-confidence cells with the LLM, never letting it invent numbers.
- **Tasks:** `extract/fallback.py` (batch ≤ 8 cells, prompt `config/prompts/fallback.md`, grounding: every number in the result appears in the raw text, reconciliation table from LLD §3.9); wire into the pipeline behind `SBCX_FALLBACK_ENABLED`.
- **Deliverables:** module, prompt, tests, live score on gold.
- **Dependencies:** M6, M7.
- **Acceptance:** fake tests for agree / override / ungrounded paths; live gold ≥ 98% field accuracy and ≤ 1.5% hallucination (or the measured value recorded with the reason); fallback cost per doc recorded.
- **Validation:** pytest + `sbcx score --set gold --fallback`.

## Phase C: Backend services and API

### M9 Persistence
- **Objective:** Store documents, extractions, summaries, catalog, premiums, comparisons, explanations, LLM calls.
- **Tasks:** `infra/db.py` (engine, session), `infra/models.py` (tables per LLD §10, JSON columns), `infra/repos.py`, `infra/storage.py` (PDF files by sha256), `create_all` on startup.
- **Deliverables:** modules + repo tests.
- **Dependencies:** M2.
- **Acceptance:** CRUD + dedupe-by-sha256 tests pass on a temp SQLite DB.
- **Validation:** pytest.

### M10 Documents API
- **Objective:** Upload and read extracted plans.
- **Tasks:** `services/ingestion.py`, `services/extraction.py` (background task, status transitions); routes `POST /documents`, `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/provenance?path=`, `GET /documents/{id}/pdf`, `DELETE /documents/{id}`.
- **Deliverables:** routes, services, integration tests.
- **Dependencies:** M6, M9 (M8 optional via flag).
- **Acceptance:** upload a gold PDF → status reaches `ready`/`extracted` → benefits equal `extract()` output; re-upload is deduped; bad files return 413/422 with codes.
- **Validation:** pytest with `TestClient`; curl.

### M11 Catalog
- **Objective:** Make marketplace plans searchable and comparable.
- **Tasks:** `services/catalog.py`; CLI `sbcx ingest-catalog` (manifest.csv + plan-attributes PUF for metal/state/type/issuer; extract each local PDF, record failures); CLI `sbcx load-premiums` (download CMS Rate PUF, store premiums by plan/rating area/age; skippable); routes `GET /catalog/plans` (filters, search, pagination), `GET /catalog/plans/{plan_id}`, `GET /catalog/facets`, `GET /catalog/plans/{plan_id}/premium?age=&rating_area=`.
- **Deliverables:** CLI, routes, tests (small fixture catalog).
- **Dependencies:** M10.
- **Acceptance:** after ingest, `GET /catalog/plans?state=TX&metal=Silver` returns extracted plans; facets correct; ingest report (ok / failed counts) recorded here.
- **Validation:** pytest + CLI run.

### M12 Section summaries
- **Objective:** Grounded plain-language summary for each of 13 sections.
- **Tasks:** `domain/enrich/sections.py` (section → paths + limitations), `domain/explain/grounding.py` (number extraction + check), `domain/enrich/summarize.py` (LLM → retry → template), cache by (sha256, parser version, prompt version, model), background step after extraction; `summaries` in `GET /documents/{id}`; `POST /documents/{id}/summaries` to regenerate.
- **Deliverables:** modules, prompt `config/prompts/summary.md`, tests.
- **Dependencies:** M7, M10.
- **Acceptance:** fake tests cover grounded / retry / template; grounding unit tests (money, %, counts, words); live run on 3 gold docs: 100% of served summaries grounded.
- **Validation:** pytest + live script.

### M13 Cost engine
- **Objective:** Exact annual cost per plan per scenario, with ranges for unknowns.
- **Tasks:** `compare/prices.py` + `config/reference_prices.yaml`; `compare/scenarios.py` + `config/scenarios.yaml` (presets low/moderate/high/baby + custom events); `compare/cost_model.py` (`member_pays`, accumulators for individual/family embedded/aggregate, simulate low/high, trace).
- **Deliverables:** modules, configs, tests.
- **Dependencies:** M2.
- **Acceptance:** the worked example in `docs/design/v2/06-cost-model.md` §8 reproduced exactly; hypothesis invariants (low ≤ high, OOP cap, monotonicity, determinism) pass.
- **Validation:** pytest (unit + property).

### M14 Comparison engine + API
- **Objective:** Deterministic `ComparisonResult` for 2–5 plans (uploads and/or catalog).
- **Tasks:** `compare/align.py`, `diff.py` (est cost per use, verdicts, flags), `rank.py`, `engine.py`; `services/comparison.py`; routes `POST /comparisons`, `GET /comparisons/{id}`, `GET /meta/scenarios`, `GET /meta/reference-prices`.
- **Deliverables:** modules, routes, tests.
- **Dependencies:** M11, M13.
- **Acceptance:** snapshot test on 2 gold plans; identical inputs → identical result hash; 422 for < 2 or > 5 plans or plans not ready.
- **Validation:** pytest.

### M15 Explanation
- **Objective:** Grounded narrative from the comparison.
- **Tasks:** `explain/factsheet.py` (trimmed result + allowed numbers), `explain/policy.py`, `explain/generate.py` (LLM → retry → Jinja template), background generation after a comparison; `explanation` + `explanation_status` in `GET /comparisons/{id}`; `POST /comparisons/{id}/explanation` to regenerate.
- **Deliverables:** modules, prompt, template, tests.
- **Dependencies:** M12, M14.
- **Acceptance:** fake tests for llm / retry / template; template output always passes grounding; live run on 3 comparisons serves only grounded output.
- **Validation:** pytest + live script.

## Phase D: Frontend

### M16 Frontend scaffold
- **Objective:** A typed, styled app shell talking to the backend.
- **Tasks:** Vite React-TS in `frontend/`; Tailwind; React Router (routes for the 5 screens); TanStack Query provider; `src/api/schema.d.ts` generated by `openapi-typescript` from the running backend (`npm run gen:api`); `src/api/client.ts` (fetch wrapper → typed errors from the envelope); layout with nav; error boundary; toaster; Vite proxy `/api → :8000`; ESLint; Vitest setup.
- **Deliverables:** `frontend/` app.
- **Dependencies:** M10 (OpenAPI available).
- **Acceptance:** `npm run build`, `npm run typecheck`, `npm run lint`, `npm test` green; health badge renders live backend status.
- **Validation:** commands + browser check.

### M17 My Plans + Plan Detail
- **Objective:** Upload plans and read them clearly.
- **Tasks:** dropzone (type/size validation, multi-file, progress, toasts); plans list with status chips and polling until ready; Plan Detail: header (issuer, plan type, period), key numbers (deductible, OOP), 13 section cards with summary + table of in/out-network cost sharing, warnings banner, click a value → provenance popover (page, source text, confidence, source); delete plan.
- **Deliverables:** pages, components, tests.
- **Dependencies:** M16, M12.
- **Acceptance:** component tests for upload validation, status polling, provenance popover; manual check with a gold PDF.
- **Validation:** Vitest + browser pane.

### M18 Catalog screen
- **Objective:** Find marketplace plans to compare.
- **Tasks:** filters (state, metal, plan type, issuer) from facets; search; paginated table; "add to comparison" (selection tray shared with uploads, max 5); catalog plan detail reuses Plan Detail.
- **Deliverables:** page, selection store, tests.
- **Dependencies:** M16, M11.
- **Acceptance:** filters update results; empty state; selection persists across pages.
- **Validation:** Vitest + browser pane.

### M19 Compare Builder + Comparison Result
- **Objective:** The core workflow: choose, configure, compare, understand.
- **Tasks:** Builder: selected plans (base choice), per-plan monthly premium (prefilled from catalog when available), employer HSA/HRA, coverage tier, scenario preset or custom event list (zod validation); submit → Result: headline cards (premium, deductible, OOP, best/worst case), scenario cost chart with low–high ranges, side-by-side diff table (filter: differences only), coverage gaps, warnings and assumptions, explanation panel (loading skeleton → LLM text or "template" badge, regenerate), "show your work" trace per scenario.
- **Deliverables:** pages, components, tests.
- **Dependencies:** M17, M18, M15.
- **Acceptance:** form validation tests; result renders ranges and verdicts; explanation states (pending / ready / template / error) tested.
- **Validation:** Vitest + browser pane.

## Phase E: Integration, testing, readiness

### M20 Integration and E2E
- **Objective:** Prove the whole workflow and its degraded modes.
- **Tasks:** `SBCX_LLM_MODE=fake` for deterministic E2E; Playwright: upload 2 gold PDFs → wait ready → add a catalog plan → compare → explanation visible; `make check-api-types` (regenerate types and diff); chaos test: no API key → template summaries/explanation, app works.
- **Deliverables:** `frontend/e2e/`, Make targets.
- **Dependencies:** M19.
- **Acceptance:** E2E green; API types up to date; degraded mode verified.
- **Validation:** `make e2e`.

### M21 Run readiness
- **Objective:** Anyone can run it locally.
- **Tasks:** root README section "Run the app"; `backend/.env.example`; Makefile (`setup`, `dev`, `test`, `lint`, `score`, `ingest-catalog`, `e2e`); `docker-compose.yml` (backend + frontend); `.github/workflows/ci.yml` (backend lint/test, frontend lint/test/build); final status in this file.
- **Deliverables:** docs and tooling.
- **Dependencies:** M20.
- **Acceptance:** fresh run following only the README works; all test suites green.
- **Validation:** run the documented commands from a clean shell.

---

## Definition of done: status

| Item | Status |
|---|---|
| All milestones implemented or documented as deferred | ✅ M0–M21 done; deviations below; deferred scope listed under Scope |
| FastAPI backend and React frontend integrated | ✅ Vite proxy in dev, nginx in Docker |
| Core workflows work end to end | ✅ Upload → extract → summaries → compare (uploads + catalog) → explanation, checked in the browser with live OpenRouter and in Playwright |
| Automated tests pass | ✅ backend 400 (pytest incl. hypothesis), frontend 13 (vitest), E2E 2 (Playwright) |
| Existing assets reused | ✅ audit_tools extractor, src/schema.py, eval/score.py, gold + v1.4 labels, OpenRouter pattern, CMS PUF |
| Setup, configuration and run steps documented | ✅ README "Run the app locally", `backend/.env.example`, `make help` |
| Runs locally from the docs | ✅ `make setup && make dev` from a fresh clone; `docker compose up --build` verified |

## Deviations and blockers log

| Date | Milestone | Note |
|---|---|---|
| 2026-10-27 | M3 | The prototype's caches (`~/audit/…`) no longer existed. Layouts are rebuilt from the PDFs (pymupdf4llm pinned to 1.28.2, the version that produced `data/markdown`; byte-identical output checked). `pdftotext` (poppler) is used when installed, as in the prototype; otherwise pdfplumber/PyMuPDF. |
| 2026-10-27 | M5 | Issuer brand lookup: the prototype took the majority issuer per family from labels. The port uses `config/issuer_brands.json` (HIOS issuer id → brand, built from the 450 reviewed docs, gold excluded), then the SBC header, then the CMS issuer name. Per-document overrides (`forcepdf.json`) were dropped. |
| 2026-10-27 | M4/M5 | New rule: "Visit 1: $X; Visit 2 and after: $Y" and "…Subsequent visits, $Y" use the later charge (v1.4 convention, previously fixed by hand in `audit_tools/fix/zz_later_rule.txt`). The gold set follows the older first-part rule for 2 such fields, so gold accuracy moves 97.0% → 96.9%. Kept, because the later charge is the right input for cost estimates. |
| 2026-10-28 | Engine | HSA-eligible and catastrophic plans apply the deductible to unmarked rows by federal rule (104 catalog plans): their ranges collapse to one number; rank agreement with SBC coverage examples baby 0.806 → 0.823, diabetes 0.682 → 0.699, fracture 0.679 → 0.714. |
| 2026-10-28 | Quality | End-to-end comparison quality review (eval/audits/2026-10-28-e2e-comparison-quality.md): engine 1.1.0 stops treating an unstated-deductible "No charge" as free (41% of plans) and uses the SBC's page-1 answer; explanations gain rankings + a superlative-claim check and explicit deductible status; UI shows plan letters. |
| 2026-10-28 | M21 | Readiness check: `docker compose` failed on Compose 2.23 (`env_file` with `required:` needs 2.24+), fixed with variable substitution and verified (build, UI, upload through nginx). `make lint` failed after running the dev server (ESLint scanned `frontend/.vite`), fixed. Production frontend deps upgraded to clear advisories: react-router-dom 7.18.4, zod 4.6.7 (+ @hookform/resolvers 5.9.1, react-hook-form 7.90.0); 0 known vulnerabilities in production deps. |
| 2026-10-27 | Audit | 200-doc accuracy audit (eval/audits/2026-10-27-random200.md) found two bugs (0% coinsurance normalization, provenance pages) and six error patterns; all fixed in parser 2.1.0: v1.4 reviewed agreement 99.5%, gold 97.0%. |
| 2026-10-27 | M21 | `docker-compose.yml` and both Dockerfiles are written but were not built or run: the Docker daemon wasn't running on the dev machine. Local run (`make setup && make dev`) is verified. |
| 2026-10-27 | M18 | Facet counts are for the whole catalog, not narrowed by the other active filters. |
| 2026-10-27 | M13 | Two rules made explicit while testing: a "No charge" cell is free even when the SBC doesn't say whether the deductible applies (otherwise the high bound charged preventive care to the deductible); and per-claim trace values keep low/high as simulated (a high-bound claim can be lower than the low-bound one once the out-of-pocket cap is hit). |
| 2026-10-27 | M8 | Fallback on gold (τ = 0.75): 11 cells sent, fixed 2 fields and broke 3 (net neutral, 96.9%). The 98% gold target isn't reached. The remaining gold errors are mostly convention differences between the gold set (guideline v1.3, row-only deductible flags) and v1.4 labels, plus a few multi-part cells. Fallback stays enabled (cheap; only low-confidence cells) and every override is shown as a warning. |

## Measurements

| Metric | Target | Measured |
|---|---|---|
| Gold field accuracy (parser only) | ≥ 96% | 96.9% (97.0% before the visit rule) |
| Gold hallucination (parser only) | ≤ 3% | 2.4% |
| v1.4 reviewed agreement | ≥ 95% | 98.7% (450 docs, 0 errors) |
| Gold field accuracy (parser + fallback) | ≥ 98% | 96.9% ⚠️ |
| Docs needing no fallback | ≥ 90% | 9 of 10 gold docs (11 cells sent in total) |
| Corpus extraction crashes | 0 | 0 of 1,829 (98.8% agreement with v1.4 on all docs) |
| Summary grounding (served) | 100% | 100% (39/39 LLM, first try, live) |
| Explanation grounding (served) | 100% | 100% (3/3 LLM, first try, live) |
