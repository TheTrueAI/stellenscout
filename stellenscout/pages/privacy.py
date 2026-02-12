"""Privacy Policy — GDPR compliant."""

import os

import streamlit as st

for key in ("IMPRESSUM_NAME", "IMPRESSUM_ADDRESS", "IMPRESSUM_EMAIL"):
    if key not in os.environ:
        try:
            os.environ[key] = st.secrets[key]
        except (KeyError, FileNotFoundError):
            pass

_name = os.environ.get("IMPRESSUM_NAME", "")
_address = os.environ.get("IMPRESSUM_ADDRESS", "")
_email = os.environ.get("IMPRESSUM_EMAIL", "")

st.set_page_config(page_title="StellenScout – Privacy Policy", page_icon="🔒")

st.title("Privacy Policy")

st.markdown(f"""
## 1. Data Controller

{_name}
{_address}
Email: {_email}

## 2. Data We Collect

### 2a. Email Digest Subscription

When you subscribe to our email digest, we process the following data:

- **Email address** — to deliver the daily job digest
- **Subscription status** — whether you have actively confirmed your subscription
- **Timestamps** — when you signed up

### 2b. CV / Resume Analysis

When you upload a CV for job matching, we process:

- **CV text content** — extracted from your uploaded file (PDF, DOCX, etc.)
- **Candidate profile** — structured data derived from your CV, including skills,
  experience level, roles, languages, education, and certifications

Your CV text and derived profile are sent to the **Google Gemini API** for
AI-powered candidate profiling and job evaluation. **Google does not use your
data to train its models** (Paid Services tier). Google may retain API inputs
and outputs for up to **30 days** solely for abuse monitoring and legal
obligations, after which they are deleted. Your uploaded CV file is not
permanently stored by StellenScout — it is processed in memory and discarded
after analysis.

For details, see Google's
[Gemini API Data Logging Policy](https://ai.google.dev/gemini-api/docs/logs-policy)
and [Gemini API Terms of Service](https://ai.google.dev/gemini-api/terms).

## 3. Legal Basis

- **Email digest:** Processing is based on your **consent** (Art. 6(1)(a) GDPR).
  You gave consent through the Double Opt-In process and may withdraw it at any
  time (see Section 8).
- **CV analysis:** Processing is based on your **consent** (Art. 6(1)(a) GDPR),
  given by uploading your CV and initiating the job search.

## 4. Third-Party Processors

We use the following services to operate StellenScout:

| Service | Provider | Purpose | Privacy Policy |
|---|---|---|---|
| **Supabase** | Supabase Inc., USA | Database (email addresses, job data) | [supabase.com/privacy](https://supabase.com/privacy) |
| **Resend** | Resend Inc., USA | Email delivery | [resend.com/legal/privacy-policy](https://resend.com/legal/privacy-policy) |
| **Streamlit** | Snowflake Inc., USA | Web application hosting | [streamlit.io/privacy-policy](https://streamlit.io/privacy-policy) |
| **Google AI (Gemini)** | Google LLC, USA | AI-powered CV analysis and job evaluation. CV text and candidate profiles are sent to the Gemini API. Data retained for up to 30 days for abuse monitoring. | [Gemini API Terms](https://ai.google.dev/gemini-api/terms) · [Data Logging Policy](https://ai.google.dev/gemini-api/docs/logs-policy) |

Data transfers to the USA are covered by each provider's Standard Contractual
Clauses (SCCs). Google's processing is governed by the
[Google Data Processing Addendum](https://cloud.google.com/terms/data-processing-addendum)
applicable to Paid Services.

## 5. Data Retention

- **Email address** — stored as long as your subscription is active. After
  unsubscribing, your record is deactivated. You may request complete deletion
  at any time (see Section 8).
- **CV / Resume** — processed in memory only; not permanently stored by
  StellenScout. Cached analysis results are stored locally on the server for up
  to 24 hours to avoid redundant processing, then automatically deleted.
- **Google Gemini API** — may retain inputs and outputs for up to 30 days for
  abuse monitoring and legal compliance.

## 6. Cookies

StellenScout does **not** use tracking cookies. Streamlit sets technically
necessary session cookies required for the application to function.

## 7. International Data Transfers

Your data may be transferred to and processed in the **United States** by the
third-party services listed in Section 4. These transfers are safeguarded by
Standard Contractual Clauses (SCCs) and, where applicable, the EU–US Data
Privacy Framework.

## 8. Your Rights (Art. 15–17, 77 GDPR)

You have the right to:

- **Access** (Art. 15 GDPR) — request what data we hold about you
- **Rectification** (Art. 16 GDPR) — correct inaccurate data
- **Erasure** (Art. 17 GDPR) — request deletion of your personal data
- **Withdraw consent** — at any time, e.g. via the unsubscribe link in every email
- **Lodge a complaint** (Art. 77 GDPR) — with a supervisory authority

Contact us at **{_email}** to exercise your rights.
""")
