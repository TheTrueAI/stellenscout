# Prefilter Benchmark: Investigation & Decision

**Status: Abandoned** — March 2026

## Motivation

Immermatch evaluates ~250 job listings per candidate per run by sending each one to
Gemini (via the evaluator agent). Gemini scores each job 0-100, writes reasoning, and
identifies missing skills. This is the highest-quality step in the pipeline, but also
the slowest and most expensive.

The idea behind prefiltering: use a cheap, pure-Python algorithm to throw away obviously
irrelevant jobs *before* calling Gemini. If we could discard even 30-50% of jobs safely,
we'd cut Gemini API costs and latency roughly in half.

The hard constraint was always: **never throw away a job that Gemini would score ≥ 60.**
A false negative — dropping a good job — is much worse than a false positive (wasting one
Gemini call on a bad job). Users would rather wait 30 extra seconds than miss a relevant
opportunity.

## What Gemini Actually Evaluates

The evaluator agent (`evaluator_agent.py`) uses a detailed scoring rubric that goes far
beyond keyword matching:

- **Language hard-cap**: If a job requires German fluency and the candidate lacks it, the
  score is capped at 30. This is the single biggest signal for candidates on the German
  job market who have B1/B2 German.
- **Temporal weighting**: Recent experience (last 3 years) and longer tenures count far
  more than old internships. A skill used 3+ years in the current role is strong evidence;
  the same skill from a 3-month internship 10 years ago is near-zero evidence.
- **Seniority mismatch**: A "Senior Data Strategy Consultant" posting for a Mid-level
  candidate with 4 years experience gets a low score, even if the skills overlap.
- **Domain reasoning**: "ESG" in a Financial Services consulting job gets a high score for
  a sustainability specialist because the domain overlaps. "ESG" in a Data Strategy job
  gets a low score. Same keyword, different meaning in context.

Any prefilter would need to approximate these signals to be useful.

## What We Tried

### Algorithms Tested

1. **BM25** — Standard information retrieval ranking. Builds a weighted query from the
   candidate profile (skills 3x, domains 3x, roles 2x) and scores each job using Okapi
   BM25 with IDF computed from the job corpus.

2. **TF-IDF cosine** — Builds TF-IDF vectors for profile and job text, computes cosine
   similarity. Same field weighting as BM25.

3. **Keyword overlap** — Percentage of profile keywords (skills, roles, domains) found in
   the job text.

4. **Composite** — TF-IDF cosine as base, with two heuristic penalties layered on top:
   - *Language penalty (×0.3)*: Regex detects German fluency requirements in job text
     (patterns like "fließend Deutsch", "Deutsch C1/C2", "verhandlungssicher"). If found
     and candidate has < C1 German, multiplies the score by 0.3 — mimicking Gemini's
     hard-cap at 30.
   - *Seniority penalty (×0.6)*: Detects Senior/Lead/Principal in job title. If the
     candidate is Mid-level, multiplies by 0.6.

All algorithms are deterministic, pure Python, no API calls.

### Benchmark Protocol

We ran two iterations of benchmarking.

**V1** tested BM25, TF-IDF, and keyword overlap on a single profile (sustainability
specialist, 259 jobs). Results were weak: best Spearman rank correlation was 0.27 (TF-IDF),
best recall at threshold 60 was 0.29 (BM25). Keyword overlap never predicted any job above
the threshold.

**V2** expanded the evaluation to be more rigorous:
- 3 candidate profiles: sustainability specialist (Mid, German B1/B2), software engineer
  (Senior, German B2), business professional (Mid, German business-fluent)
- 774 total job evaluations across profiles
- 20/80 dev/test split with fixed random seed to prevent overfitting
- Added the composite algorithm
- 95% bootstrap confidence intervals (1,000 resamples) on ranking metrics
- Multiple threshold analysis (T=50, 60, 70, 80)

## Results

The only metric that matters for our use case: **how many bad jobs (Gemini < 60) can each
algorithm discard without accidentally throwing away any good jobs (Gemini ≥ 60)?**

### Strict mode: lose zero good jobs

| Profile | Test jobs | Good | Bad | BM25 | TF-IDF | Keyword | **Composite** |
|---|---|---|---|---|---|---|---|
| profile_biz | 180 | 61 | 119 | 0 (0%) | 0 (0%) | 0 (0%) | **0 (0%)** |
| profile_sus | 208 | 20 | 188 | 21 (11%) | 17 (9%) | 7 (4%) | **42 (22%)** |
| profile_sw | 233 | 60 | 173 | 15 (9%) | 11 (6%) | 9 (5%) | **21 (12%)** |

Composite wins on every profile, but the savings are modest: 0-22% of bad jobs discarded.
For profile_biz, every algorithm scores 0% — one outlier job ("Produktmanager Warning
Sensors", Gemini scored it 72) gets an algorithm score of 0, which forces the safe
threshold to zero and blocks any filtering.

### Relaxed mode: lose at most 1 good job

| Profile | BM25 | TF-IDF | Keyword | **Composite** |
|---|---|---|---|---|
| profile_biz | 11 (9%) | 5 (4%) | 6 (5%) | 9 (8%) |
| profile_sus | 70 (37%) | 148 (79%) | 27 (14%) | 93 (49%) |
| profile_sw | 15 (9%) | 11 (6%) | 28 (16%) | 24 (14%) |

Allowing just 1 good job to slip through opens up dramatically better filtering for some
profiles (profile_sus: composite jumps from 22% to 49%). But it's inconsistent — profile_biz
and profile_sw still barely reach 10%.

### Ranking quality (for reference)

| Algorithm | Spearman ρ (macro avg) | Kendall τ | NDCG@20 |
|---|---|---|---|
| BM25 | 0.225 | 0.157 | 0.662 |
| TF-IDF | 0.255 | 0.178 | 0.624 |
| Keyword overlap | 0.180 | 0.127 | 0.661 |
| **Composite** | **0.286** | **0.200** | **0.689** |

The acceptance bar we set was Spearman ρ ≥ 0.50 and recall ≥ 0.90. Best achieved: ρ = 0.29.

## Why It Doesn't Work

The fundamental problem is that **token-matching algorithms cannot replicate Gemini's
domain reasoning**. Specific failure modes:

1. **Semantic gaps**: Gemini understands that "Produktmanager Warning Sensors" is relevant
   to a business profile (product management domain overlap) even though almost no tokens
   match. Token-based algorithms score it 0.

2. **Context-dependent keywords**: "ESG" in a Financial Services consulting job is relevant
   to a sustainability specialist. "ESG" in a Data Strategy role is not. Same token,
   completely different meaning. Algorithms can't distinguish.

3. **One outlier ruins everything**: The strict safety constraint means a single
   false-negative (one good job scored 0 by the algorithm) forces the safe threshold to 0
   for the entire profile. This happened for profile_biz.

4. **Language detection is heuristic**: The regex-based German fluency detection helps
   significantly for profile_sus (B1/B2 candidate, many C1/C2 jobs) but doesn't generalize
   to other language pairs or less standardized job postings.

5. **The improvement ceiling is low**: Even the composite algorithm with hand-crafted
   heuristics for the two biggest Gemini signals (language and seniority) only reaches
   ρ = 0.29. Pure lexical methods probably max out around ρ ≈ 0.35-0.40 for this task.

## Approaches Not Tried

These could theoretically close the gap but were not pursued:

- **Sentence embeddings** (e.g. `all-MiniLM-L6-v2`): Would capture semantic similarity
  without token overlap. Adds a model dependency and inference cost, partially defeating
  the purpose of a "cheap" prefilter.

- **Calibration** (isotonic regression): Mapping algorithm scores to Gemini-like scores
  on the dev set. Would help threshold-based filtering but not ranking quality.

- **Feature stacking**: Combining TF-IDF, language penalty, seniority penalty, and
  embedding similarity as features in a simple classifier trained on dev set. Most
  promising approach, but adds complexity for uncertain gains.

## Decision: Abandon Prefiltering

**We are not pursuing prefiltering further.** The reasons:

1. **The safety constraint makes it nearly useless.** With "lose zero good jobs", the best
   algorithm saves 0-22% of Gemini calls depending on the profile. That's 0-50 fewer calls
   out of 250 — saving maybe 5-15 seconds of wall-clock time and a few cents of API cost.

2. **It's unreliable across profiles.** Composite works reasonably for profile_sus (22%)
   but does nothing for profile_biz (0%). We can't deploy a prefilter that silently fails
   for some users.

3. **The complexity isn't justified.** Maintaining heuristic rules (language detection
   regexes, seniority patterns), benchmark infrastructure, and algorithm code adds
   ongoing maintenance cost for marginal and inconsistent savings.

4. **Better alternatives exist.** Instead of filtering *after* search, we can improve
   *search query quality* (fewer irrelevant jobs returned in the first place) or batch
   Gemini calls more efficiently. Both approaches are simpler and more reliable.

The experimental benchmarking code that supported this investigation has been removed
from this repository and is no longer part of the active codebase.
