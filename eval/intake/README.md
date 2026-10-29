# Usage intake evaluation set (v2.1 T4.1)

`cases.jsonl`: descriptions of a year of care with the events a careful person would enter
(`event`, `count`, `member`) and the phrases that should be reported as not included (`expected_unmodeled`,
matched case-insensitively against the returned quotes).

**Status: draft.** The 40 cases were drafted by Claude on 2026-10-29 so the evaluation could run during
implementation. T4.1 asks for cases written by a person: review every case (especially the expected counts
and the judgement calls tagged `condition`, `synonym`, `preventive` and `past-vs-future`), add cases from
real users' wording, and record the reviewer here. `SBCX_INTAKE_ENABLED` stays `false` until a reviewed set
meets the D6 targets.

Judgement calls in the draft:
- c10, c37: a flu shot is listed as not included (no event type); a screening colonoscopy counts as a preventive visit.
- c32: a CT scan maps to the "MRI / CT scan" event.
- c25: care that happened last year is not counted.
- c31: a misspelled tier ("generik pills") still counts as generic.
- c16: a medicine taken all year in 90-day supplies is 12 fills of 30 days.

Run: `cd backend && uv run python ../eval/intake/run.py` (uses OpenRouter; about $0.0005 per case).
