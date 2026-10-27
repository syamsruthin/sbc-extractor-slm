# Architecture: SBC Plan Comparison v2

Diagrams are Mermaid and render on GitHub. Detail per component is in [03-HLD](03-HLD.md)
and [04-LLD](04-LLD.md).

## 1. Architectural principles

1. **Deterministic core, probabilistic edges.** Parsing, normalization, validation, comparison
   and money math are plain Python. LLMs are only at the edges: re-reading ambiguous cells,
   writing summaries, writing the explanation.
2. **LLM output is never trusted blindly.** Every LLM output passes a schema check and a
   grounding check against the data it was given. Every LLM step has a non-LLM fallback.
3. **One contract per boundary.** `BenefitsDocument` (extraction → everything else) and
   `ComparisonResult` (engine → explanation/UI). Both are versioned Pydantic models.
4. **Provenance everywhere.** Every value carries where it came from (page, cell text,
   parser rule, or LLM fallback).
5. **Cache by content.** Documents are keyed by SHA-256. Extraction, summaries and catalog
   entries are computed once per (hash, version).
6. **Provider-agnostic LLM layer.** One client interface over vLLM (self-hosted SLM),
   OpenRouter and Anthropic, all using the OpenAI-compatible or native structured-output APIs.

## 2. System context (C4 level 1)

```mermaid
flowchart LR
    user(["👤 Plan shopper / employee"])
    advisor(["👤 Benefits advisor"])
    op(["👤 Operator"])

    subgraph sys ["SBC Plan Comparison v2"]
        core["Upload · Extract · Summarize · Compare · Explain"]
    end

    cms[("CMS Marketplace PUFs<br/>Plan Attributes + Rate")]
    issuers[("Issuer websites<br/>SBC PDFs")]
    llm["LLM providers<br/>vLLM (self-hosted SLM)<br/>Hosted API (OpenRouter / Anthropic)"]

    user -->|"uploads SBC PDFs,<br/>enters premiums + usage"| core
    advisor -->|"compares client options"| core
    op -->|"batch catalog ingest,<br/>quality dashboards"| core
    core -->|"SBC URLs, premiums"| cms
    core -->|"downloads SBC PDFs (catalog)"| issuers
    core -->|"fallback cells, summaries,<br/>explanations"| llm
```

## 3. Containers (C4 level 2)

```mermaid
flowchart TB
    subgraph client ["Client"]
        ui["Web UI<br/>(frontend/: React + Vite + TS)<br/>upload · side-by-side · scenarios · explanation · PDF viewer"]
    end

    subgraph api ["API layer"]
        gw["FastAPI service<br/>REST + SSE<br/>auth, rate limits, validation"]
    end

    subgraph workers ["Workers (same codebase, queue consumers)"]
        ext["Extraction worker<br/>PDF → layout → anchors → cells<br/>→ BenefitsDocument"]
        fb["Fallback extractor<br/>cell-level LLM, guided JSON"]
        sum["Section summarizer<br/>small LLM, grounded"]
        cmp["Comparison + cost engine<br/>pure Python"]
        exp["Explanation generator<br/>LLM + grounding validator<br/>+ template fallback"]
        batch["Catalog batch ingester<br/>PUF → download → extract"]
    end

    subgraph data ["Data"]
        pg[("PostgreSQL<br/>documents, extractions (JSONB),<br/>summaries, catalog, premiums,<br/>comparisons, explanations, llm_calls")]
        obj[("Object storage<br/>PDFs, page images,<br/>layout cache")]
        q[("Queue<br/>Redis (RQ/Arq)")]
        cfg[("Versioned config<br/>reference_prices.yaml,<br/>scenarios.yaml, prompts/, legal_limits.yaml")]
    end

    subgraph llmz ["LLM serving"]
        vllm["vLLM<br/>Qwen3 SLM (+LoRA)<br/>structured outputs"]
        hosted["Hosted LLM API"]
    end

    ui -->|"HTTPS JSON / multipart"| gw
    gw -->|"enqueue jobs"| q
    gw <-->|"read/write"| pg
    gw -->|"put PDF"| obj
    q --> ext & sum & exp & batch
    ext --> fb
    ext --> pg
    ext --> obj
    fb --> llmrouter
    sum --> llmrouter
    exp --> llmrouter
    gw -->|"sync call (fast)"| cmp
    cmp --> pg
    cmp --> cfg
    exp --> pg
    batch --> ext
    llmrouter{{"LLM client<br/>router + retries + cost log"}} --> vllm & hosted
```

**Why the comparison engine runs synchronously in the API:** it's pure CPU work on two to five
small JSON documents (< 200 ms), so queueing it would only add latency. Extraction and
LLM steps take seconds and go through the queue.

## 4. End-to-end data flow

```mermaid
flowchart LR
    pdf["SBC PDF"] --> L["1 · Layout<br/>pdfplumber tables + text<br/>pymupdf4llm markdown"]
    L --> S["2 · Segment<br/>header · Important Questions ·<br/>services table · drugs ·<br/>exclusions · coverage examples"]
    S --> A["3 · Anchor rows<br/>26 template services<br/>+ drug tiers"]
    A --> C["4 · Parse cells<br/>price tokens, parts,<br/>deductible flags"]
    C --> V["5 · Assemble + normalize<br/>+ validate + confidence"]
    V -->|"confidence < τ"| F["5b · LLM fallback<br/>(cell only)"]
    F --> V
    V --> BD[["BenefitsDocument v2"]]
    BD --> SM["6 · Section summaries<br/>small LLM + grounding"]
    SM --> BD2[["BenefitsDocument v2<br/>+ summaries"]]
    BD2 --> CE["7 · Comparison + cost engine<br/>align · diff · simulate · rank"]
    U["User inputs<br/>premiums, HSA/HRA,<br/>usage profile"] --> CE
    RP["Reference prices<br/>+ scenarios"] --> CE
    CE --> CR[["ComparisonResult"]]
    CR --> EX["8 · Explanation<br/>LLM + numeric grounding<br/>→ template fallback"]
    EX --> OUT[["Explanation + comparison<br/>→ UI"]]
```

## 5. Where LLMs are used (and where they are not)

| Step | LLM? | Model class | Input size | Why |
|---|---|---|---|---|
| Layout, segmentation, anchoring, cell parsing | No | — | — | Fixed CMS template; regex + table structure is exact and fast |
| Cell fallback | Yes, ≤ 10% of docs, few cells each | OpenRouter (configurable, `SBCX_MODEL_FALLBACK`) | ~150 tokens/cell | Long-tail cell wording the rules don't cover |
| Section summaries | Yes, 13 calls/doc (parallel), cached | OpenRouter (`SBCX_MODEL_SUMMARY`) | ~300–600 tokens/section | Turns limitations text into readable sentences |
| Comparison, cost simulation, ranking | **No** | — | — | Money math must be exact and auditable |
| Explanation | Yes, 1 call per comparison | OpenRouter (`SBCX_MODEL_EXPLANATION`) | ~2–4k tokens | Narrative quality matters most here |

## 6. Deployment view

```mermaid
flowchart TB
    subgraph dev ["Local dev (Mac)"]
        d1["uv run uvicorn api"]
        d2["SQLite + local files"]
        d3["MLX or hosted LLM"]
    end

    subgraph prod ["Hosted (e.g. Fly.io / Render / k8s)"]
        lb["HTTPS load balancer"]
        apis["API pods ×2"]
        wk["Worker pods ×N<br/>(autoscale on queue depth)"]
        rds[("Managed Postgres")]
        redis[("Managed Redis")]
        s3[("S3-compatible bucket")]
    end

    subgraph gpu ["GPU serving (Modal)"]
        vl["vLLM: Qwen3 + LoRA adapters<br/>(summarizer, fallback)<br/>scale-to-zero"]
    end

    ext_llm["Hosted LLM API"]

    lb --> apis --> rds & redis & s3
    wk --> rds & redis & s3
    wk --> vl
    wk --> ext_llm
```

- **MVP:** single container (API + in-process worker via FastAPI background tasks), SQLite,
  local disk, hosted LLM. No GPU needed.
- **Scale-up:** split workers, Postgres, Redis queue, Modal vLLM for the SLM (matches the
  existing Phase 5–6 plan in [00-compute-plan](../../00-compute-plan.md)).

## 7. Mapping to the current repository

| Existing asset | Role in v2 |
|---|---|
| `src/schema.py` (`SBCExtraction`, `normalize`) | Core of `BenefitsDocument.benefits`; unchanged field paths, so `eval/score.py` keeps working |
| `audit_tools/ext.py`, `mk.py`, `excl.py`, `parse.py`, `tables.py`, `mdclean.py` | Prototype for the parser. Ported into `src/sbcx/parse/` with tests |
| `audit_tools/fix/*.txt` + `data/labels/v1.4/_corrections.jsonl` | Catalog of parser failure patterns. Each pattern becomes a rule + a regression test |
| `data/labels/v1.4` (1,829 docs, 450 + 105 reviewed) | Parser regression corpus |
| `data/gold` (10 docs, PDF-verified) | Acceptance test set (unchanged) |
| `eval/score.py` | Scores parser output exactly like model output |
| `src/collect_sbcs.py`, `download_split.py` | Catalog batch ingester inputs |
| `training/*` (QLoRA, vLLM eval) | Retargeted to cell-fallback + summarizer SLMs ([09-decisions](09-decisions.md) ADR-009) |
