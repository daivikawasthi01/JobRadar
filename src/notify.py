"""Email and webhook alerting for JobRadar."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import html
import logging
import os
from pathlib import Path
import smtplib
import sqlite3
import urllib.request
import urllib.error
from src.config import ConfigError
from src.filters import parse_grad_years
from src.store import decompress_description

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def load_env_file(path: str = ".env") -> None:
    """Helper to populate os.environ from a local .env file if present."""
    p = Path(path)
    if not p.exists():
        return
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception as e:
        logger.warning("Could not read .env file: %s", e)


def format_exp(min_exp: float | None, max_exp: float | None) -> str:
    """Format experience requirement as '0-2', '2+', or '?'."""
    if min_exp is not None and max_exp is not None:
        mn = int(min_exp) if min_exp.is_integer() else min_exp
        mx = int(max_exp) if max_exp.is_integer() else max_exp
        return f"{mn}-{mx}"
    if min_exp is not None:
        mn = int(min_exp) if min_exp.is_integer() else min_exp
        return f"{mn}+"
    return "?"


def utc_to_ist_str(utc_iso: str | None) -> str:
    """Convert UTC ISO timestamp to formatted IST display string."""
    if not utc_iso:
        return ""
    try:
        dt_utc = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        return dt_ist.strftime("%d %b %H:%M IST")
    except Exception:
        return utc_iso


def build_email(rows: list[sqlite3.Row], now_utc: str) -> tuple[str, str, str]:
    """Pure function building subject, text body, and HTML body for alert emails.

    - Subject: [New Job] {N} new matches: {Company1}, {Company2}, {Company3}… (max 3 names, then …)
    - HTML body: table with Role | Company | Location | Exp | Posted | Apply
    - Times shown in IST. All fields HTML-escaped.
    """
    if not rows:
        return ("[New Job] 0 new matches", "No new jobs.", "<p>No new jobs.</p>")

    # Collect distinct company names in order of appearance
    seen_companies: list[str] = []
    for r in rows:
        comp_name = r["company"]
        if comp_name not in seen_companies:
            seen_companies.append(comp_name)

    if len(seen_companies) <= 3:
        comp_summary = ", ".join(seen_companies)
    else:
        comp_summary = ", ".join(seen_companies[:3]) + "…"

    subject = f"[New Job] {len(rows)} new matches: {comp_summary}"

    # Plain text body
    text_lines = [
        f"JobRadar detected {len(rows)} new fresher/entry-level job(s):",
        "",
    ]
    for r in rows:
        exp_disp = format_exp(r["min_exp"], r["max_exp"])
        batch_disp = format_batch_year(r)
        posted_disp = utc_to_ist_str(r["posted_at"]) or "Recently"
        text_lines.append(
            f"- {r['title']} at {r['company']} ({r['location'] or 'Location unspecified'}) "
            f"[Exp: {exp_disp}, Batch year: {batch_disp}, Posted: {posted_disp}]"
        )
        text_lines.append(f"  Apply: {r['url']}")
        text_lines.append("")

    text_body = "\n".join(text_lines)

    # HTML body
    table_rows = []
    for r in rows:
        title_esc = html.escape(str(r["title"]))
        comp_esc = html.escape(str(r["company"]))
        loc_esc = html.escape(str(r["location"] or "Unspecified"))
        exp_esc = html.escape(format_exp(r["min_exp"], r["max_exp"]))
        batch_esc = html.escape(format_batch_year(r))
        posted_esc = html.escape(utc_to_ist_str(r["posted_at"]) or "Recently")
        url_esc = html.escape(str(r["url"]))

        table_rows.append(
            f"<tr>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0;'><strong>{title_esc}</strong></td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0;'>{comp_esc}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0;'>{loc_esc}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: center;'>{exp_esc}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: center;'>{batch_esc}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0; white-space: nowrap;'>{posted_esc}</td>"
            f"<td style='padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: center;'>"
            f"<a href='{url_esc}' style='background-color: #2563eb; color: #ffffff; padding: 4px 10px; text-decoration: none; border-radius: 4px; font-weight: 500;' target='_blank'>Apply</a>"
            f"</td>"
            f"</tr>"
        )

    rows_html = "\n".join(table_rows)
    html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(subject)}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; color: #1e293b; margin: 0; padding: 20px; background-color: #f8fafc;">
  <div style="max-width: 900px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 24px;">
    <h2 style="margin-top: 0; color: #0f172a; font-size: 20px;">JobRadar Alert: {len(rows)} New Match(es)</h2>
    <p style="color: #64748b; font-size: 14px; margin-bottom: 20px;">New entry-level / fresher roles discovered on company career pages.</p>
    <table style="width: 100%; border-collapse: collapse; font-size: 14px; text-align: left;">
      <thead>
        <tr style="background-color: #f1f5f9; color: #475569;">
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1;">Role</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1;">Company</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1;">Location</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1; text-align: center;">Exp</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1; text-align: center;">Batch year</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1;">Posted</th>
          <th style="padding: 10px 8px; border-bottom: 2px solid #cbd5e1; text-align: center;">Apply</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
    <div style="margin-top: 24px; font-size: 12px; color: #94a3b8; text-align: center; border-top: 1px solid #f1f5f9; padding-top: 16px;">
      JobRadar automated crawl • Times in IST
    </div>
  </div>
</body>
</html>"""

    return (subject, text_body, html_body)


def format_batch_year(row: sqlite3.Row) -> str:
    """Show detected graduation years or explicitly mark them as unspecified."""
    keys = row.keys()
    title = str(row["title"]) if "title" in keys else ""
    description = row["description"] if "description" in keys else ""
    if isinstance(description, bytes):
        description = decompress_description(description)
    years = sorted(parse_grad_years(title, str(description or "")))
    return ", ".join(str(year) for year in years) if years else "Not specified"


def send_email(
    subject: str,
    text: str,
    html_content: str,
    attachments: list[tuple[str, bytes]] | None = None,
) -> None:
    """Send email alert via Gmail SMTP over SSL (port 465)."""
    load_env_file()

    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    alert_to = os.environ.get("ALERT_TO")

    if not user or not password or not alert_to:
        missing = [k for k in ["GMAIL_USER", "GMAIL_APP_PASSWORD", "ALERT_TO"] if not os.environ.get(k)]
        raise ConfigError(
            f"Missing required email environment variable(s): {', '.join(missing)}. "
            f"Ensure they are set in your environment or in a .env file."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = alert_to
    msg.set_content(text)
    msg.add_alternative(html_content, subtype="html")

    if attachments:
        for fname, data in attachments:
            msg.add_attachment(
                data,
                maintype="application",
                subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=fname,
            )

    logger.info("Sending email to %s: '%s'", alert_to, subject)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    logger.info("Email sent successfully.")


def send_ntfy(topic: str, title: str, message: str) -> None:
    """Send an optional notification to ntfy.sh."""
    if not topic or not topic.strip():
        return
    url = f"https://ntfy.sh/{topic.strip()}"
    req = urllib.request.Request(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "User-Agent": "JobRadar/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("ntfy push sent to topic '%s' (status %d)", topic, resp.status)
    except Exception as e:
        logger.warning("Failed to send ntfy push to %s: %s", topic, e)
