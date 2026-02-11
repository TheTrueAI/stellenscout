"""Email module using Resend for StellenScout daily digests."""

import os
from datetime import datetime, timezone

import resend


def _build_job_row(job: dict) -> str:
    """Return an HTML table row for a single job."""
    score = job.get("score")
    badge_color = "#22c55e" if (score or 0) >= 80 else "#eab308" if (score or 0) >= 70 else "#f97316"
    score_html = (
        f'<span style="background:{badge_color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-weight:bold">{score}/100</span>'
        if score
        else ""
    )
    apply_url = job.get("url", "#")

    return f"""
    <tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:12px 8px;vertical-align:top">
        <strong>{job["title"]}</strong><br>
        <span style="color:#6b7280">{job["company"]}</span>
      </td>
      <td style="padding:12px 8px;text-align:center;vertical-align:top">
        {score_html}
      </td>
      <td style="padding:12px 8px;text-align:center;vertical-align:top">
        <a href="{apply_url}"
           style="color:#2563eb;text-decoration:none;font-weight:600">
          View &rarr;
        </a>
      </td>
    </tr>"""


def _build_html(jobs: list[dict]) -> str:
    """Build a full HTML email body for the daily digest."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    rows = "\n".join(_build_job_row(j) for j in jobs)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f9fafb">

  <div style="max-width:600px;margin:24px auto;background:#fff;
              border-radius:8px;overflow:hidden;
              border:1px solid #e5e7eb">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);
                padding:24px;color:#fff;text-align:center">
      <h1 style="margin:0;font-size:22px">StellenScout Daily Digest</h1>
      <p style="margin:4px 0 0;opacity:.85;font-size:14px">{today}</p>
    </div>

    <!-- Body -->
    <div style="padding:24px">
      <p style="margin:0 0 16px;color:#374151">
        We found <strong>{len(jobs)}</strong> new job match{"es" if len(jobs) != 1 else ""}
        for you today:
      </p>

      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="border-bottom:2px solid #e5e7eb">
            <th style="text-align:left;padding:8px;color:#6b7280;
                        font-size:12px;text-transform:uppercase">Position</th>
            <th style="text-align:center;padding:8px;color:#6b7280;
                        font-size:12px;text-transform:uppercase">Score</th>
            <th style="text-align:center;padding:8px;color:#6b7280;
                        font-size:12px;text-transform:uppercase">Link</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:16px 24px;background:#f9fafb;
                border-top:1px solid #e5e7eb;text-align:center;
                color:#9ca3af;font-size:12px">
      Sent by StellenScout &middot; AI-powered job matching for Europe
    </div>
  </div>

</body>
</html>"""


def send_daily_digest(user_email: str, jobs: list[dict]) -> dict:
    """Send a daily digest email with new job matches.

    Args:
        user_email: Recipient email address.
        jobs: List of job dicts, each with at least ``title``, ``company``,
              ``url``, and optionally ``score``.

    Returns:
        Resend API response dict.

    Raises:
        ValueError: If RESEND_API_KEY is not set.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise ValueError("RESEND_API_KEY environment variable not set")

    resend.api_key = api_key

    from_addr = os.environ.get("RESEND_FROM", "StellenScout <digest@stellenscout.dev>")

    return resend.Emails.send(
        {
            "from": from_addr,
            "to": [user_email],
            "subject": f"StellenScout: {len(jobs)} new job match{'es' if len(jobs) != 1 else ''} for you",
            "html": _build_html(jobs),
        }
    )
