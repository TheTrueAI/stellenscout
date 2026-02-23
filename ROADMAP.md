# StellenScout — Next Steps Roadmap

Based on the current state (private repo, hosted on Streamlit Community Cloud) and the goals outlined in AGENTS.md, here's a prioritized plan:

---

## Phase 0: Pre-Launch Hardening (Do Before Going Public)

### 0.1 — Testing & CI
- [x] **Write unit tests** for core modules: `llm.py`, `cache.py`, `cv_parser.py`, `db.py`, `search_agent.py`, `evaluator_agent.py` (mock API calls) — 146 tests across 9 test files
- [ ] **Write integration tests** for the full pipeline (profile → queries → search → evaluate → summary) using fixture CVs
- [x] **Set up GitHub Actions CI** — run `pytest` on every push/PR, lint with `ruff`
- [x] **Add type checking** — run `mypy` in CI (Pydantic models already help here)

### 0.2 — Security Audit
- [x] **Audit secrets handling** — raw exceptions no longer leak in `st.error()` calls; all user-facing errors are generic with server-side `logger.exception()`; subscriber emails redacted from `daily_task.py` logs (replaced with subscriber UUID)
- [x] **Review Supabase RLS policies** — 6 explicit policies applied: anon key denied on `subscribers` and `job_sent_logs`; `jobs` allows anon SELECT only; Supabase security advisor shows zero warnings
- [x] **Rate-limit hardening** — added IP-based rate limiting (module-level dict in `app.py`) alongside the existing 30-second session cooldown; extracts client IP from `X-Forwarded-For`; stale entries cleaned after 5 minutes
- [x] **Input sanitization** — PDF page limit (50 pages), DOCX paragraph limit (2000), email format regex validation before `add_subscriber()`; existing guards retained (5 MB file limit, extension whitelist, 50K char truncation)

### 0.3 — GDPR Compliance Checklist
- [x] **Verify data deletion works end-to-end** — test expiry, unsubscribe, and purge flows (38 tests in `tests/test_db.py`)
- [x] **Finalize privacy policy** (`pages/privacy.py`) — make it legally accurate for your jurisdiction
- [x] **Finalize impressum** (`pages/impressum.py`) — required by German law (§ 5 DDG)
- [x] **Cookie banner** — not required: only Streamlit's technically necessary session cookies (exempt under ePrivacy Art. 5(3)); `gatherUsageStats = false`; no analytics/tracking

---

## Phase 1: Public Launch (Free)

### 1.1 — Open Source the Repo
- [x] **Add LICENSE file** (AGPL-3.0) to repo root
- [x] **Write README.md** — hero screenshot, what it does, self-hosting instructions (`GOOGLE_API_KEY`, `SERPAPI_KEY`, `SUPABASE_*`, `RESEND_*`), link to live demo
- [x] **Write CONTRIBUTING.md** — how to set up local dev, PR process, code style
- [x] **Create GitHub issue templates** — bug report, feature request, question
- [ ] **Flip repo to public**

### 1.2 — Deploy Daily Digest
- [x] **Set up GitHub Actions cron job** for daily_task.py (e.g., `cron: '0 7 * * *'` UTC)
- [ ] **Add secrets to GitHub Actions** — all required env vars from §10
- [ ] **Test the full digest cycle** — subscribe, verify, receive digest, unsubscribe
- [ ] **Monitor SerpAPI quota** — 100 searches/month on free tier; track usage per run

### 1.3 — UX Quick Wins
- [ ] **Personalize the UI** — greet user by first name extracted from CV profile
- [ ] **Add "Edit Profile" step** — let user tweak skills/roles/preferences before searching (this is already in Open Issues)
- [ ] **Add a "Preferences" text input** — free-form like *"I want remote fintech jobs, no big corporations"* → append to Headhunter prompt
- [ ] **Show job age warning** — if `posted_at` is >30 days, badge it as "possibly expired"
- [ ] **Improve job cards** — show apply links more prominently, add company logos via Clearbit/Logo.dev
- [ ] **Add digest preferences UI** — allow users to change `min_score` and cadence (daily/weekly) after subscription

### 1.4 — Monitoring & Observability
- [ ] **Add structured logging** — replace `print()` with `logging` module, include run IDs
- [ ] **Track pipeline metrics** — jobs found per query, avg scores, API latency, cache hit rates
- [ ] **Set up error alerting** — GitHub Actions failure notifications (email or Slack webhook)
- [ ] **Add cost dashboard** — track daily SerpAPI + Gemini usage and estimated monthly spend

---

## Phase 2: Monetization (Paid Newsletter)

### 2.1 — Stripe Integration
- [ ] **Create Stripe product** — monthly subscription (€5–9/month)
- [ ] **Add Stripe Checkout flow** — after DOI confirmation, redirect to payment
- [ ] **Store subscription status in DB** — add `stripe_customer_id`, `stripe_subscription_id`, `payment_status` columns to `subscribers`
- [ ] **Stripe webhook handler** — handle `invoice.paid`, `customer.subscription.deleted`, `invoice.payment_failed`
- [ ] **Gate daily digest** behind active payment — free tier gets one-time search only

### 2.2 — Free vs Paid Tiers
| Feature | Free | Paid (€5-9/mo) |
|---|---|---|
| One-time job search | ✅ | ✅ |
| Daily digest email | ❌ | ✅ |
| Results per search | 20 jobs | 50 jobs |
| Score threshold | Fixed 70 | Configurable |
| Query editing | ❌ | ✅ |

### 2.3 — Migrate Off Streamlit Community Cloud
- [ ] **Move to a VPS or PaaS** — Railway, Fly.io, or Hetzner (Streamlit Cloud has no custom domain, no Stripe webhooks, limited control)
- [ ] **Custom domain** — e.g., `stellenscout.de` or `stellenscout.eu`
- [ ] **Reverse proxy** — Caddy or nginx with automatic HTTPS
- [ ] **Docker Compose setup** — `app`, `daily-task` (cron), `postgres` (or keep Supabase)

---

## Phase 3: Growth & Scale

### 3.1 — SerpAPI Cost Optimization (Open Issue)
- [ ] **Deduplicate queries more aggressively** — normalize queries before searching, semantic dedup
- [ ] **Cache search results in DB per (query, location, date)** — share across subscribers
- [ ] **Evaluate alternative search APIs** — Google Custom Search, Bing Jobs API, or direct scraping as fallback
- [ ] **Implement search budget per run** — e.g., max 20 API calls/day total across all subscribers
- [ ] **Add adaptive query stopping** — stop low-yield queries early based on jobs-per-call threshold
- [ ] **Reuse cross-day popular query results** — short TTL for high-volume locations to reduce repeated calls

### 3.2 — Stale Job Detection (Open Issue)
- [ ] **HEAD request validation** — before including a job, check if the apply URL returns 200
- [ ] **Track job first-seen date in DB** — auto-expire jobs older than 45 days
- [ ] **User feedback loop** — "This job no longer exists" button → mark as expired in DB
- [ ] **Add portal quality scoring** — down-rank sources with high dead-link rates and low apply success

### 3.3 — Multi-CV Support (Open Issue)
- [ ] **Allow multiple profiles per subscriber** — each with its own search queries and evaluation criteria
- [ ] **Separate digest sections** — "Software Engineering matches" vs "Data Science matches"

### 3.4 — Search & Evaluation Pipeline Efficiency (Open Issue)
- [ ] **Prototype streaming evaluation** — evaluate jobs incrementally while parsing search results
- [ ] **Benchmark architecture variants** — compare (search→batch-eval) vs (search+stream-eval) for latency/cost/quality
- [ ] **Gate LLM evaluations with cheap heuristics** — skip obvious mismatches before Gemini scoring
- [ ] **Add A/B quality checks** — ensure optimization changes don’t reduce top-match relevance

### 3.5 — Community & Marketing
- [ ] **Write a launch blog post** — "I built an AI job hunter with Gemini" for Hacker News / Reddit / Dev.to
- [ ] **Record a 2-minute demo video** for the README
- [ ] **Post on LinkedIn** — target the German tech community
- [ ] **Submit to Product Hunt** once paid tier is live

### 3.6 — Reliability & Abuse Protection (Potential Risks)
- [ ] **Add idempotency keys for pipeline runs** — prevent duplicate digests/emails on retries
- [ ] **Implement provider fallback strategy** — graceful degradation when Gemini/SerpAPI is down
- [ ] **Add anti-abuse controls** — basic bot detection and per-email/IP throttling around upload/subscribe endpoints
- [ ] **Set SLOs + runbooks** — define uptime/error budgets and incident response steps for digest failures

---

## Suggested Priority Order (Next 4 Weeks)

| Week | Focus |
|---|---|
| **Week 1** | Unit tests + CI pipeline + security audit |
| **Week 2** | README, CONTRIBUTING, LICENSE, issue templates → **go public** |
| **Week 3** | Deploy daily digest on GitHub Actions, test end-to-end |
| **Week 4** | UX quick wins (preferences input, edit profile, personalization) |

After that, move to Phase 2 (Stripe) when you have ~20+ newsletter subscribers to validate demand.
