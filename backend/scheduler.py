import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="Europe/Brussels")


def start_scheduler():
    _scheduler.add_job(
        _send_daily_orders,
        CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone="Europe/Brussels"),
        id="daily_order_email",
        replace_existing=True,
    )
    _scheduler.add_job(
        _refresh_menu,
        CronTrigger(hour=7, minute=30, day_of_week="mon-fri", timezone="Europe/Brussels"),
        id="daily_menu_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler gestart (dagelijkse mail om 10:00, menu refresh om 08:00)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown()


def _send_daily_orders():
    from backend.database import SessionLocal
    from backend.email_service import send_order_email
    from backend.models import DailySummary, Order

    db = SessionLocal()
    try:
        today = date.today()
        summary = db.query(DailySummary).filter(DailySummary.date == today).first()

        if summary and summary.email_sent:
            return

        orders = db.query(Order).filter(Order.date == today).all()
        if not orders:
            logger.info("Geen bestellingen voor %s, mail overgeslagen", today)
            return

        success = send_order_email(orders, today)
        if success:
            if not summary:
                summary = DailySummary(date=today)
                db.add(summary)
            summary.email_sent = True
            summary.email_sent_at = datetime.utcnow()
            db.commit()
            logger.info("Dagelijkse bestelling verstuurd voor %s", today)
    finally:
        db.close()


def _refresh_menu():
    from backend.database import SessionLocal
    from backend.models import MenuItem
    from backend.scraper import scrape_menu

    db = SessionLocal()
    try:
        items = scrape_menu()
        if items:
            db.query(MenuItem).delete()
            for data in items:
                db.add(MenuItem(
                    name=data["name"],
                    category=data["category"],
                    price=data.get("price"),
                    description=data.get("description"),
                    available=True,
                ))
            db.commit()
            logger.info("Menu bijgewerkt: %d items", len(items))
    finally:
        db.close()
