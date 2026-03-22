# Immermatch — Strategy Roadmap (March 2026 Refresh)

This roadmap replaces the old launch-phase plan and reflects current reality:
- The product is already public.
- Main risk is **relevance + trust** (wrong location behavior, stale/weak links, confusing UX transitions).
- Growth is currently constrained more by product quality and conversion friction than by missing monetization.

---

## 1) Current Priority Lens (Impact First)

1. ~~Search relevance and location consistency~~ *(done — R1, R2, R3, R4)*
2. ~~UX clarity during pipeline transitions~~ *(done — R1, R3)*
3. ~~Digest reliability and subscription data lifecycle~~ *(done — R5, R6, R7)*
4. **Subscription safety: token split + schema foundation** *(R8 — in progress)*
5. **Growth instrumentation: measure impact of R1–R7, then decide next investments** *(R9, R10)*
6. **Architecture debt — only after data from step 5** *(R11, R12)*
7. **Monetization readiness (de-prioritized until usage signal improves)**

---

## 2) Impact × Effort Triage (Active Problems)

| ID | Problem | Impact | Effort | Status |
|---|---|---|---|---|
| R1 | Sidebar location updates too late; transition feels unclear while CV extraction is still running | High | Medium | **Done** |
| R2 | `Cologne` vs `Köln`, `Munich` vs `München` produce different outcomes | High | Medium | **Done** |
| R3 | `✅ Queries generated` expander appears empty during search | Medium | Small | **Done** |
| R4 | Jobs appear mixed across city searches (homepage symptom) | High | Medium | **Done** |
| R5 | BA listings include useless homepage links (`https://www.arbeitsagentur.de/`) | High | Medium | **Done** |
| R6 | Unsubscribe should hard-delete subscriber record, not only set `is_active=false` | High | Medium | **Done** |
| R7 | Digest reliability gap: avoid wrong-city jobs and mark-as-sent only after successful send | High | Medium | **Done** |
| R8 | Confirmation token and manage-token collision in DB schema | High | Medium | **Do now** |
| R9 | Low user count; no privacy-safe funnel instrumentation for actionable growth work | High | Medium | **Do now** |
| R10 | GitHub issues and milestones are stale vs real priorities | High | Small | **Do now** |
| R11 | `app.py` is a 1,500-line god file; pipeline logic duplicated between `app.py` and `daily_task.py` | High | Large | **After R9 data** |
| R12 | File-based `ResultCache` breaks on multi-instance deploys, leaks across users sharing same CV hash | Medium | Medium | **After R9 data** |

---

## 3) Execution Plan (Next 4 Weeks, Step-by-Step)

### Week 1 — Relevance + UX Friction Removal

#### R1 — Sidebar location synchronization + transition clarity (#67)
- [x] **Step 1:** Document current UI state machine for `location` input (idle, extracting CV, ready, submitted, searching).
- [x] **Step 2:** Define one canonical source-of-truth session key for location state and submission state.
- [x] **Step 3:** Disable location input and submit CTA immediately after submit event is accepted.
- [x] **Step 4:** Update CTA labels/spinner text per phase (extracting, generating queries, searching, evaluating).
- [x] **Step 5:** Add UI test that verifies disabled state and label transitions.
- [x] **Done when:** No ambiguous editable state remains after submit, and transition labels match actual pipeline phase.

#### R3 — Query expander visibility during active search (#68)
- [x] **Step 1:** Identify where generated queries are first available in session state.
- [x] **Step 2:** Persist query list immediately when generated (before downstream pipeline completes).
- [x] **Step 3:** Render persisted query list in expander during active search/evaluation.
- [x] **Step 4:** Keep list visible on reruns unless a new search run explicitly resets it.
- [x] **Step 5:** Add UI regression test for non-empty expander during active run.
- [x] **Done when:** `✅ Queries generated` always shows generated queries as soon as they exist.

#### R4 — Wrong-city carryover on consecutive searches (#70)
- [x] **Step 1:** Reproduce with deterministic sequence (Munich → Berlin, Köln → München, etc.) and record expected/actual.
- [ ] **Step 2:** Trace city-specific state through cache keying, session state, and rendering pipeline.
- [x] **Step 3:** Ensure city-scoped result containers are reset or replaced on location change.
- [x] **Step 4:** Validate that UI cards use current run output only, not stale prior-run fragments.
- [x] **Step 5:** Add regression test for two consecutive city searches in one session.
- [x] **Done when:** Second search only shows jobs from second city according to configured location policy.

#### R2 — Canonical location aliases (#66)
- [x] **Step 1:** Define normalization table for priority aliases (`Köln/Cologne`, `München/Munich`).
- [x] **Step 2:** Normalize at input boundary (before query generation/provider selection).
- [x] **Step 3:** Ensure normalized value is used consistently in cache keys, provider calls, and logs.
- [x] **Step 4:** Add tests for alias equivalence and cache-key consistency.
- [x] **Step 5:** Add short note in docs describing normalization behavior.
- [x] **Done when:** Alias pairs produce equivalent behavior and deterministic cache reuse.

### Week 2 — Link Quality + Subscription Lifecycle Correctness

#### R5 — BA homepage-link filtering (#40)
- [x] **Step 1:** Define rules for non-actionable links (homepage-only, generic landing redirects).
- [x] **Step 2:** Apply filtering in BA parsing/link-validation path before UI rendering.
- [x] **Step 3:** Preserve valid alternative links when one option is filtered.
- [x] **Step 4:** Add test fixtures with mixed valid + homepage links.
- [x] **Done when:** No BA job card shows `https://www.arbeitsagentur.de/` as an apply option.

#### R6 — Unsubscribe hard-delete policy (#69)
- [x] **Step 1:** Confirm DB referential path for deleting subscriber row safely.
- [x] **Step 2:** Implement hard-delete on unsubscribe endpoint/service path.
- [x] **Step 3:** Update privacy/unsubscribe copy so behavior and text are identical.
- [x] **Step 4:** Add tests for successful hard-delete and missing-token/error behavior.
- [x] **Step 5:** Verify no personal fields remain after unsubscribe flow completion.
- [x] **Done when:** Unsubscribe removes subscriber row and aligns with user-facing legal text.

#### R7 — Digest correctness and send/log integrity (#44)
- [x] **Step 1:** Define correct operation order: candidate selection → send → log sent.
- [x] **Step 2:** Guard against logging jobs as sent if email delivery fails.
- [x] **Step 3:** Enforce subscriber-location relevance filter before evaluation/send stage.
- [x] **Step 4:** Add retry/idempotency guard for digest run duplication risk.
- [x] **Step 5:** Add tests for send-failure path, retry path, and location relevance.
- [x] **Done when:** No send/log mismatch and no wrong-location digest entries in tested scenarios.

### Phase 3 — Subscription Safety + Schema Foundation

#### R8 — Token split for DOI vs manage links (#71)
- [ ] **Step 1:** Add dedicated `manage_token` and `manage_token_expires_at` schema fields.
- [ ] **Step 2:** Add migration file(s) and schema documentation update.
- [ ] **Step 3:** Move manage-link issuance/validation to new token columns.
- [ ] **Step 4:** Keep DOI confirmation flow exclusively on confirmation token columns.
- [ ] **Step 5:** Add tests for concurrent DOI + manage-link lifecycle.
- [ ] **Done when:** Manage-link generation no longer overwrites DOI confirmation tokens.

#### DB schema versioning follow-through
- [ ] **Step 1:** Introduce version-controlled migration directory/process (Supabase SQL).
- [ ] **Step 2:** Backfill current schema as an initial baseline migration.
- [ ] **Step 3:** Add contributor docs for applying migrations locally and in deployment.
- [ ] **Done when:** Schema changes are code-reviewed and reproducible from repo state.

### Phase 4 — Measure Impact + Growth Instrumentation

> R1–R7 shipped a wave of quality fixes. Before investing in large refactors, measure whether those fixes moved conversion — otherwise we're optimizing blind.

#### R9 — Privacy-safe funnel instrumentation (#31)
- [ ] **Step 1:** Define exact funnel events and event dictionary (no PII fields).
- [ ] **Step 2:** Implement event emission at each funnel boundary.
- [ ] **Step 3:** Build weekly aggregate report (conversion per stage + drop-off deltas).
- [ ] **Step 4:** Validate data retention window and privacy policy consistency.
- [ ] **Done when:** Weekly funnel report exists and is usable for prioritization decisions.

#### Roadmap checkpoint (R10)
- [ ] **Step 1:** Review all active issues for impact/effort drift.
- [ ] **Step 2:** Close, defer, or split oversized issues into executable units.
- [ ] **Step 3:** Re-rank the next sprint backlog using current KPIs.
- [ ] **Done when:** Open issue list reflects only near-term, execution-ready work.

#### Growth experiments (#43)
- [ ] **Step 1:** Propose 3 experiments with hypothesis, owner, and expected KPI shift.
- [ ] **Step 2:** Run at least 2 experiments within the week.
- [ ] **Step 3:** Record outcomes using a simple win/learn/kill template.
- [ ] **Step 4:** Fold insights into next roadmap revision.
- [ ] **Done when:** At least 2 measured experiments are completed and reviewed.

### Phase 5 — Architecture Debt (informed by Phase 4 data)

> Sequence these based on what funnel data reveals. If conversion is strong, R11/R12 improve maintainability for the next growth push. If conversion is weak, revisit whether these are the right investments.

#### R11 — Extract pipeline service layer
- [ ] **Step 1:** Identify shared logic between `app.py:_run_pipeline()` and `daily_task.py:main()` — dedup, URL extraction, evaluation orchestration, "already seen" tracking.
- [ ] **Step 2:** Extract a `PipelineService` (or similar) in `immermatch/pipeline.py` that encapsulates search→evaluate→filter with progress callbacks (no Streamlit dependency).
- [ ] **Step 3:** Refactor `app.py:_run_pipeline()` to call the service, keeping only UI concerns (progress bars, status widgets, card rendering).
- [ ] **Step 4:** Refactor `daily_task.py:main()` to call the same service, keeping only cron/email concerns.
- [ ] **Step 5:** Split remaining `app.py` concerns (subscription flow, rate limiting, profile editing) into focused modules.
- [ ] **Step 6:** Add tests for the extracted service independent of Streamlit.
- [ ] **Done when:** `app.py` is under 500 lines, `daily_task.py` shares orchestration code with the UI, and a new entry point (CLI, API) can call the pipeline without importing Streamlit.

#### R12 — Replace file-based cache with DB-backed storage
- [ ] **Step 1:** Audit current `ResultCache` usage — profile, queries, jobs (date-keyed), evaluations (profile-keyed).
- [ ] **Step 2:** Design DB tables or key-value storage for each cache type with proper TTL and per-user isolation.
- [ ] **Step 3:** Implement new cache backend behind the existing `ResultCache` interface.
- [ ] **Step 4:** Migrate `app.py` and pipeline to use DB-backed cache; remove `.immermatch_cache/` filesystem dependency.
- [ ] **Step 5:** Add tests for cache isolation (two users, same CV hash) and TTL expiry.
- [ ] **Done when:** No local filesystem cache is required, and multi-instance deployment works without shared disk.

#### Digest SLOs and runbooks (#45)
- [ ] **Step 1:** Define 2–4 reliability SLOs (timeliness, send success, duplicate rate, failure recovery time).
- [ ] **Step 2:** Define alert thresholds and owner/escalation expectations.
- [ ] **Step 3:** Write incident runbook for provider/API/DB/email failure classes.
- [ ] **Step 4:** Add post-incident review template.
- [ ] **Done when:** SLOs and runbooks are documented and linked from operations docs.

---

## 4) KPI Targets (April 2026 Checkpoint)

### Product Quality KPIs
- Wrong-location complaint rate: **< 2%** of sessions
- BA homepage-link exposure: **0%** in displayed results
- Digest send-to-log mismatch incidents: **0**
- Unsubscribe hard-delete success: **100%** (auditable)

### Conversion & Growth KPIs
- CV upload → first search completion: **+20%** vs current baseline
- Search completion → newsletter subscribe: **+30%** vs current baseline
- DOI completion rate: **> 60%**

---

## 5) Backlog Governance (GitHub Hygiene)

### Rules
- Roadmap is the source of truth for priorities; issues must map to one active roadmap item.
- Every issue needs: impact, effort, owner, success metric, and revisit date.
- Close or defer issues that are not relevant in the next 4–6 weeks.

### Cadence
- **Weekly**: triage open issues, re-rank by impact/effort, close stale items.
- **Bi-weekly**: roadmap checkpoint with KPI delta.

### Active GitHub Issues (Execution Set)
- #67 — Location input UX and transition state clarity
- #66 — Location alias canonicalization (`Köln/Cologne`, `München/Munich`)
- #68 — Query expander visibility during active search
- #70 — Wrong-city carryover between consecutive searches
- #40 — BA link hygiene (discard homepage-only links)
- #69 — Unsubscribe hard-delete policy
- #44 — Digest correctness and idempotency
- #71 — Token split (`confirmation_token` vs manage token)
- #31 — Privacy-safe funnel metrics
- #43 — Short-cycle growth experiments
- R11 — Extract pipeline service layer (`app.py` god file + duplicated pipeline)
- R12 — Replace file-based cache with DB-backed storage

---

## 6) Deferred (Only After Demand Signal)

The following remain important but are intentionally de-prioritized until product quality and user traction improve:
- Stripe and paid tier rollout
- Infrastructure migration (VPS/PaaS)
- Multi-CV support
- Advanced evaluation optimization/A-B experimentation

Trigger for activation: sustained usage and clear conversion signal (e.g., stable subscriber growth and digest engagement over multiple weeks).

---

## 7) Decision Log

- **Date:** 2026-03-19
- **Hypothesis:** With R1–R7 quality fixes shipped, measuring their impact before investing in large refactors (R11, R12) will lead to better prioritization.
- **Evidence:** R1–R7 all completed. No funnel data exists yet to confirm whether fixes moved conversion. R8 is a real bug (token collision breaks DOI). R11/R12 are large internal efforts with no direct user-facing impact.
- **Decision:** Reorder remaining work: R8 + schema versioning first (fix the bug), then R9/R10 (measure + recalibrate), then R11/R12 (refactor only if data supports it). Replaced fixed week numbering with phases since original timeline has drifted.
- **KPI impact expected:** Faster DOI fix improves subscription conversion; earlier instrumentation enables data-driven decisions for architecture investment.
- **Revisit date:** 2026-04-03

---

- **Date:** 2026-03-06
- **Hypothesis:** Fixing relevance/trust and UX transition friction will improve conversion more than shipping monetization now.
- **Evidence:** User feedback on location inconsistency, mixed-city results, empty query expander, weak link quality, and stale issue backlog.
- **Decision:** Re-prioritize next 4 weeks to quality/reliability + balanced growth instrumentation.
- **KPI impact expected:** Higher search completion, higher subscribe + DOI conversion, fewer trust-breaking mismatches.
- **Revisit date:** 2026-04-03
