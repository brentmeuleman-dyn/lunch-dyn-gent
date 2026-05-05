import logging
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)


def send_order_email(orders: list, order_date: date) -> bool:
    """Stuur de geconsolideerde bestelling naar de broodjesbar."""
    if not orders:
        return False

    subject = f"Bestelling Dynapps Gent – {order_date.strftime('%d/%m/%Y')}"
    body = _compose_body(orders, order_date)
    return _send(to=settings.SHOP_EMAIL, subject=subject, body=body)


def _compose_body(orders: list, order_date: date) -> str:
    lines = [
        "Goedemorgen,",
        "",
        f"Hierbij onze bestelling voor {order_date.strftime('%A %d/%m/%Y')}:",
        "",
    ]

    for order in orders:
        for item in order.items:
            qty = item.get("quantity", 1)
            name = item.get("name", "")
            notes = item.get("notes", "")
            line = f"- {qty}x {name}"
            if notes:
                line += f"  ({notes})"
            lines.append(line)
        if order.notes:
            lines.append(f"  Opmerking: {order.notes}")
    lines.append("")

    lines += [
        f"Totaal: {len(orders)} personen",
        "",
        "Met vriendelijke groeten,",
        "Dynapps Gent",
    ]
    return "\n".join(lines)


def _send(to: str, subject: str, body: str, cc: Optional[str] = None) -> bool:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.error("SMTP niet geconfigureerd – stel SMTP_USER en SMTP_PASSWORD in via .env")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = settings.FROM_EMAIL or settings.SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            recipients = [to] + ([cc] if cc else [])
            server.sendmail(settings.SMTP_USER, recipients, msg.as_string())

        logger.info("E-mail verstuurd naar %s: %s", to, subject)
        return True

    except Exception as e:
        logger.error("E-mail versturen mislukt naar %s: %s", to, e)
        return False
