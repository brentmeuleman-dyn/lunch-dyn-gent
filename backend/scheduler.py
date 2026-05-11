import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="Europe/Brussels")


def start_scheduler():
    _scheduler.add_job(
        _refresh_menu,
        CronTrigger(hour=7, minute=30, day_of_week="mon-fri", timezone="Europe/Brussels"),
        id="daily_menu_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler gestart (menu refresh om 07:30)")


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown()



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
                    garnish_price=data.get("garnish_price"),
                    description=data.get("description"),
                    available=True,
                ))
            db.commit()
            logger.info("Menu bijgewerkt: %d items", len(items))
    finally:
        db.close()
