"""Email module using Resend for StellenScout daily digests."""

import os
from datetime import datetime, timezone
from html import escape as _esc

import resend


def _safe_url(url: str) -> str:
    """Sanitise a URL for use in an HTML href attribute.

    Only ``http`` and ``https`` schemes are allowed.  Anything else
    (e.g. ``javascript:``, ``data:``) is replaced with ``#``.
    """
    stripped = url.strip()
    if stripped and not stripped.lower().startswith(("http://", "https://")):
        return "#"
    return _esc(stripped, quote=True)


def _build_job_row(job: dict) -> str:
    """Return an HTML card block for a single job."""
    score = job.get("score")
    badge_color = "#22c55e" if (score or 0) >= 80 else "#eab308" if (score or 0) >= 70 else "#f97316"
    score_html = (
        f'<span style="background:{badge_color};color:#fff;padding:4px 12px;'
        f'border-radius:12px;font-weight:bold;font-size:13px">{score}/100</span>'
        if score
        else ""
    )
    apply_url = _safe_url(job.get("url", "#"))
    location = _esc(job.get("location", ""))
    location_html = (
        f'<div style="color:#6b7280;font-size:13px;margin-top:4px">&#128205; {location}</div>' if location else ""
    )
    title = _esc(job.get("title", ""))
    company = _esc(job.get("company", ""))

    return f"""
    <tr><td style="padding:6px 0">
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;
                  padding:16px;margin:0">
        <table style="width:100%;border-collapse:collapse"><tr>
          <td style="vertical-align:top">
            <div style="font-weight:bold;font-size:15px;color:#111827">{title}</div>
            <div style="color:#6b7280;font-size:14px;margin-top:2px">{company}</div>
            {location_html}
          </td>
          <td style="vertical-align:top;text-align:right;white-space:nowrap;padding-left:12px">
            {score_html}
          </td>
        </tr></table>
        <div style="margin-top:12px">
          <a href="{apply_url}"
             style="background:#2563eb;color:#fff;padding:8px 20px;
                    border-radius:6px;text-decoration:none;font-weight:600;
                    font-size:13px;display:inline-block">
            View Job &rarr;
          </a>
        </div>
      </div>
    </td></tr>"""


def _impressum_line() -> str:
    """Return a one-line HTML-safe impressum string for email footers (§ 5 DDG)."""
    name = _esc(os.environ.get("IMPRESSUM_NAME", ""))
    address = _esc(os.environ.get("IMPRESSUM_ADDRESS", "").replace("\n", ", "))
    email = _esc(os.environ.get("IMPRESSUM_EMAIL", ""))
    parts = [p for p in (name, address, email) if p]
    return " · ".join(parts) if parts else "StellenScout"


def _build_html(jobs: list[dict], unsubscribe_url: str = "", target_location: str = "") -> str:
    """Build a full HTML email body for the daily digest."""
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    rows = "\n".join(_build_job_row(j) for j in jobs)
    impressum = _impressum_line()

    safe_location = _esc(target_location)
    location_subtitle = (
        f'<p style="margin:4px 0 0;opacity:.85;font-size:14px">Jobs in {safe_location}</p>' if safe_location else ""
    )

    excellent = sum(1 for j in jobs if (j.get("score") or 0) >= 80)
    good = sum(1 for j in jobs if 70 <= (j.get("score") or 0) < 80)
    stats_parts: list[str] = []
    if excellent:
        stats_parts.append(
            f'<span style="background:#22c55e;color:#fff;padding:2px 10px;'
            f'border-radius:12px;font-size:12px;font-weight:bold">'
            f"{excellent} excellent</span>"
        )
    if good:
        stats_parts.append(
            f'<span style="background:#eab308;color:#fff;padding:2px 10px;'
            f'border-radius:12px;font-size:12px;font-weight:bold">'
            f"{good} good</span>"
        )
    stats_html = f'<p style="margin:8px 0 0">{" ".join(stats_parts)}</p>' if stats_parts else ""

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f9fafb">

  <div style="max-width:600px;margin:24px auto;background:#fff;
              border-radius:8px;overflow:hidden;
              border:1px solid #e5e7eb">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);
                padding:24px;color:#fff;text-align:center">
      <h1 style="margin:0;font-size:22px">&#128270; StellenScout Daily Digest</h1>
      <p style="margin:4px 0 0;opacity:.85;font-size:14px">{today}</p>
      {location_subtitle}
    </div>

    <!-- Body -->
    <div style="padding:24px">
      <p style="margin:0 0 4px;color:#374151">
        We found <strong>{len(jobs)}</strong> new job match{"es" if len(jobs) != 1 else ""}
        for you today:
      </p>
      {stats_html}

      <table style="width:100%;border-collapse:separate;border-spacing:0 4px;margin-top:16px">
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="padding:16px 24px;background:#f9fafb;
                border-top:1px solid #e5e7eb;text-align:center;
                color:#9ca3af;font-size:12px">
      <p style="margin:0 0 8px">You're receiving this because you subscribed to StellenScout.</p>
      {impressum}
      {f'<br><a href="{_safe_url(unsubscribe_url)}" style="color:#9ca3af">Unsubscribe</a>' if unsubscribe_url else ""}
    </div>
  </div>

</body>
</html>"""


def send_daily_digest(
    user_email: str,
    jobs: list[dict],
    unsubscribe_url: str = "",
    target_location: str = "",
) -> dict:
    """Send a daily digest email with new job matches.

    Args:
        user_email: Recipient email address.
        jobs: List of job dicts, each with at least ``title``, ``company``,
              ``url``, and optionally ``score`` and ``location``.
        unsubscribe_url: One-click unsubscribe link for this subscriber.
        target_location: Subscriber's target job location (shown in header).

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

    params: dict = {
        "from": from_addr,
        "to": [user_email],
        "subject": f"StellenScout: {len(jobs)} new job match{'es' if len(jobs) != 1 else ''} for you",
        "html": _build_html(jobs, unsubscribe_url=unsubscribe_url, target_location=target_location),
    }
    if unsubscribe_url:
        params["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

    return resend.Emails.send(params)


def send_welcome_email(
    email: str,
    target_location: str = "",
    subscription_days: int = 30,
    privacy_url: str = "",
    unsubscribe_url: str = "",
) -> dict:
    """Send a welcome email after successful DOI confirmation.

    Args:
        email: Recipient email address.
        target_location: Subscriber's target job location.
        subscription_days: Duration of the subscription in days.
        privacy_url: URL to the privacy policy page.
        unsubscribe_url: One-click unsubscribe link for this subscriber.

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
    impressum = _impressum_line()

    safe_location = _esc(target_location)
    location_line = (
        f'<tr><td style="padding:8px 12px">'
        f'<span style="color:#6b7280;font-size:18px;vertical-align:middle">&#128205;</span> '
        f"Daily AI-matched jobs in <strong>{safe_location}</strong></td></tr>"
        if safe_location
        else ""
    )
    safe_privacy_url = _safe_url(privacy_url) if privacy_url else ""
    privacy_line = f'<a href="{safe_privacy_url}" style="color:#9ca3af">Privacy Policy</a>' if safe_privacy_url else ""
    unsub_html = (
        f'<a href="{_safe_url(unsubscribe_url)}" style="color:#9ca3af">Unsubscribe</a>' if unsubscribe_url else ""
    )
    footer_links = " · ".join(link for link in (privacy_line, unsub_html) if link)
    footer_links_html = f"<br>{footer_links}" if footer_links else ""

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f9fafb">
  <div style="max-width:600px;margin:24px auto;background:#fff;
              border-radius:8px;overflow:hidden;
              border:1px solid #e5e7eb">
    <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);
                padding:32px 24px;color:#fff;text-align:center">
      <div style="font-size:36px;margin-bottom:8px">&#127881;</div>
      <h1 style="margin:0;font-size:24px">Welcome to StellenScout</h1>
      <p style="margin:8px 0 0;opacity:.85;font-size:15px">Your subscription is confirmed</p>
    </div>
    <div style="padding:24px">
      <p style="font-size:16px;color:#374151;margin:0 0 16px">
        Your daily job digest is now active. Here's what to expect:</p>
      <table style="width:100%;border-collapse:collapse;background:#f9fafb;
                    border:1px solid #e5e7eb;border-radius:8px;overflow:hidden">
        {location_line}
        <tr><td style="padding:8px 12px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#128197;</span>
          Subscription runs for <strong>{subscription_days} days</strong>, then expires automatically</td></tr>
        <tr><td style="padding:8px 12px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#9993;&#65039;</span>
          First digest arrives <strong>tomorrow morning</strong></td></tr>
        <tr><td style="padding:8px 12px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#128275;</span>
          Unsubscribe any time via the link in each email</td></tr>
      </table>
    </div>
    <div style="padding:16px 24px;background:#f9fafb;
                border-top:1px solid #e5e7eb;text-align:center;
                color:#9ca3af;font-size:12px">
      {impressum}
      {footer_links_html}
    </div>
  </div>
</body>
</html>"""

    params: dict = {
        "from": from_addr,
        "to": [email],
        "subject": "Welcome to StellenScout \u2014 your daily digest starts tomorrow",
        "html": html,
    }
    if unsubscribe_url:
        params["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

    return resend.Emails.send(params)


def send_verification_email(email: str, verify_url: str) -> dict:  # type: ignore[type-arg]
    """Send a Double Opt-In verification email.

    Args:
        email: Recipient email address.
        verify_url: Full URL the user must visit to confirm their subscription.

    Returns:
        Resend API response dict.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise ValueError("RESEND_API_KEY environment variable not set")

    resend.api_key = api_key
    from_addr = os.environ.get("RESEND_FROM", "StellenScout <digest@stellenscout.dev>")
    impressum = _impressum_line()

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,
'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f9fafb">
  <div style="max-width:600px;margin:24px auto;background:#fff;
              border-radius:8px;overflow:hidden;
              border:1px solid #e5e7eb">
    <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);
                padding:32px 24px;color:#fff;text-align:center">
      <div style="font-size:36px;margin-bottom:8px">&#128270;</div>
      <h1 style="margin:0;font-size:24px">StellenScout</h1>
      <p style="margin:8px 0 0;opacity:.85;font-size:15px">One click to activate your daily job digest</p>
    </div>
    <div style="padding:24px">
      <p style="font-size:16px;color:#374151;margin:0 0 16px">
        Thank you for subscribing! Please confirm your email address to start
        receiving AI-matched job listings:</p>
      <p style="text-align:center;margin:24px 0">
        <a href="{_safe_url(verify_url)}"
           style="background:#2563eb;color:#fff;padding:14px 36px;
                  border-radius:6px;text-decoration:none;font-weight:600;
                  font-size:16px;display:inline-block">
          Confirm subscription &#10003;
        </a>
      </p>
      <table style="width:100%;border-collapse:collapse;background:#f9fafb;
                    border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;
                    margin:20px 0 16px">
        <tr><td style="padding:8px 12px;color:#374151;font-size:14px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#128640;</span>
          AI scores every job against your CV</td></tr>
        <tr><td style="padding:8px 12px;color:#374151;font-size:14px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#9993;&#65039;</span>
          Daily digest with your best matches</td></tr>
        <tr><td style="padding:8px 12px;color:#374151;font-size:14px">
          <span style="color:#6b7280;font-size:18px;vertical-align:middle">&#128275;</span>
          Unsubscribe any time, data deleted automatically</td></tr>
      </table>
      <p style="color:#6b7280;font-size:13px;margin:0">
        This link is valid for <strong>24 hours</strong>. If you did not
        sign up, you can safely ignore this email.
      </p>
    </div>
    <div style="padding:16px 24px;background:#f9fafb;
                border-top:1px solid #e5e7eb;text-align:center;
                color:#9ca3af;font-size:12px">
      {impressum}
    </div>
  </div>
</body>
</html>"""

    return resend.Emails.send(
        {
            "from": from_addr,
            "to": [email],
            "subject": "StellenScout: Please confirm your email address",
            "html": html,
        }
    )
