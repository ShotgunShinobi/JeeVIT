"""
Notification dispatch for Hot leads.

Provides:
  • ConsoleNotifier  — logs to stdout (default, no config needed)
  • Documented stubs for Telegram, Slack, and Email

To switch providers, set the NOTIFIER env var and supply the
corresponding credentials (see .env.example).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from .models import ScoredLead


# ---------------------------------------------------------------------------
# Protocol / interface
# ---------------------------------------------------------------------------

class Notifier(Protocol):
    """Send a notification about a lead.  Returns True on success."""

    def notify(self, lead: ScoredLead) -> bool: ...


# ---------------------------------------------------------------------------
# Console notifier  (default)
# ---------------------------------------------------------------------------

class ConsoleNotifier:
    """Print Hot-lead alerts to stdout. Zero config required."""

    def notify(self, lead: ScoredLead) -> bool:
        border = "=" * 60
        alert_text = (
            f"\n{border}\n"
            f"[HOT LEAD ALERT] >>> High-Priority Lead Detected\n"
            f"{border}\n"
            f"  Name:       {lead.name}\n"
            f"  Company:    {lead.company}\n"
            f"  Email:      {lead.email or '(none)'}\n"
            f"  Message:    {lead.message[:120]}{'...' if len(lead.message) > 120 else ''}\n"
            f"  Reasoning:  {lead.llm_reasoning}\n"
            f"  Lead ID:    {lead.lead_id}\n"
            f"{border}\n"
        )
        try:
            print(alert_text)
        except UnicodeEncodeError:
            print(alert_text.encode("ascii", errors="replace").decode("ascii"))
        return True


# ---------------------------------------------------------------------------
# Telegram notifier  (documented stub)
# ---------------------------------------------------------------------------

# class TelegramNotifier:
#     """Send Hot-lead alerts via Telegram bot.
#
#     Requires:
#       TELEGRAM_BOT_TOKEN  – from @BotFather
#       TELEGRAM_CHAT_ID    – your chat / group ID
#
#     Usage:
#       notifier = TelegramNotifier(
#           bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
#           chat_id=os.getenv("TELEGRAM_CHAT_ID"),
#       )
#     """
#
#     def __init__(self, bot_token: str, chat_id: str):
#         self.bot_token = bot_token
#         self.chat_id = chat_id
#
#     def notify(self, lead: ScoredLead) -> bool:
#         import requests
#         text = (
#             f"🔥 *HOT LEAD*\n"
#             f"*Name:* {lead.name}\n"
#             f"*Company:* {lead.company}\n"
#             f"*Email:* {lead.email or '(none)'}\n"
#             f"*Message:* {lead.message[:200]}\n"
#             f"*Lead ID:* {lead.lead_id}"
#         )
#         url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
#         resp = requests.post(url, json={
#             "chat_id": self.chat_id,
#             "text": text,
#             "parse_mode": "Markdown",
#         })
#         return resp.ok


# ---------------------------------------------------------------------------
# Slack notifier  (documented stub)
# ---------------------------------------------------------------------------

# class SlackNotifier:
#     """Send Hot-lead alerts to a Slack channel via webhook.
#
#     Requires:
#       SLACK_WEBHOOK_URL  – Incoming Webhook URL from Slack app config
#
#     Usage:
#       notifier = SlackNotifier(
#           webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
#       )
#     """
#
#     def __init__(self, webhook_url: str):
#         self.webhook_url = webhook_url
#
#     def notify(self, lead: ScoredLead) -> bool:
#         import requests
#         payload = {
#             "text": f"🔥 *HOT LEAD* — {lead.name} at {lead.company}",
#             "blocks": [
#                 {
#                     "type": "section",
#                     "text": {
#                         "type": "mrkdwn",
#                         "text": (
#                             f"*🔥 HOT LEAD*\n"
#                             f">*Name:* {lead.name}\n"
#                             f">*Company:* {lead.company}\n"
#                             f">*Email:* {lead.email or '(none)'}\n"
#                             f">*Message:* {lead.message[:200]}\n"
#                             f">*Lead ID:* {lead.lead_id}"
#                         ),
#                     },
#                 }
#             ],
#         }
#         resp = requests.post(self.webhook_url, json=payload)
#         return resp.ok


# ---------------------------------------------------------------------------
# Email notifier  (documented stub)
# ---------------------------------------------------------------------------

# class EmailNotifier:
#     """Send Hot-lead alerts via SMTP email.
#
#     Requires:
#       SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
#       NOTIFICATION_EMAIL (recipient)
#
#     Usage:
#       notifier = EmailNotifier(
#           host=os.getenv("SMTP_HOST"),
#           port=int(os.getenv("SMTP_PORT", "587")),
#           user=os.getenv("SMTP_USER"),
#           password=os.getenv("SMTP_PASSWORD"),
#           to_email=os.getenv("NOTIFICATION_EMAIL"),
#       )
#     """
#
#     def __init__(self, host, port, user, password, to_email):
#         self.host = host
#         self.port = port
#         self.user = user
#         self.password = password
#         self.to_email = to_email
#
#     def notify(self, lead: ScoredLead) -> bool:
#         import smtplib
#         from email.mime.text import MIMEText
#
#         body = (
#             f"HOT LEAD ALERT\n\n"
#             f"Name:    {lead.name}\n"
#             f"Company: {lead.company}\n"
#             f"Email:   {lead.email or '(none)'}\n"
#             f"Message: {lead.message}\n"
#             f"Lead ID: {lead.lead_id}\n"
#         )
#         msg = MIMEText(body)
#         msg["Subject"] = f"🔥 Hot Lead: {lead.name} ({lead.company})"
#         msg["From"] = self.user
#         msg["To"] = self.to_email
#
#         with smtplib.SMTP(self.host, self.port) as server:
#             server.starttls()
#             server.login(self.user, self.password)
#             server.sendmail(self.user, self.to_email, msg.as_string())
#         return True


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_notifier(provider: str = "console", **kwargs) -> Notifier:
    """Create a notifier instance based on the provider name.

    Supported: 'console'  (default)
    Documented: 'telegram', 'slack', 'email'
    """
    if provider == "console":
        return ConsoleNotifier()
    # Uncomment and configure when ready:
    # elif provider == "telegram":
    #     return TelegramNotifier(**kwargs)
    # elif provider == "slack":
    #     return SlackNotifier(**kwargs)
    # elif provider == "email":
    #     return EmailNotifier(**kwargs)
    else:
        print(f"⚠️  Unknown notifier '{provider}', falling back to console.")
        return ConsoleNotifier()
