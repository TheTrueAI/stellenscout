When writing tests for a module in `immermatch/`:

1. **File naming:** Create `tests/test_<module>.py`
2. **Imports:** Import the module under test and fixtures from `conftest.py`
3. **Mock all external services** — never call real APIs:
   - Gemini: `@patch("immermatch.<module>.call_gemini")`
   - Supabase: `@patch("immermatch.db.get_admin_client")`
   - Resend: `@patch("immermatch.emailer.resend")`
   - SerpApi: `@patch("immermatch.serpapi_provider.serpapi_search")`
   - Bundesagentur: `@patch("immermatch.bundesagentur.requests.get")`
4. **Use shared fixtures** from `tests/conftest.py`:
   - `sample_profile` — `CandidateProfile` with work history
   - `sample_job` — `JobListing` with apply options
   - `sample_evaluation` — `JobEvaluation` (score 85)
   - `sample_evaluated_job` — composite `EvaluatedJob`
5. **Test fixture files** (sample CVs, text) go in `tests/fixtures/`
6. **Cover edge cases:** empty inputs, API errors, invalid JSON, missing fields
7. **Run after writing:**
   ```bash
   source .venv/bin/activate && pytest tests/test_<module>.py -x -q
   ```
