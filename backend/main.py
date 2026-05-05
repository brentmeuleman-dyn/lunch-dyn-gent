import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db, init_db
from backend.models import DailySummary, MenuItem, Order
from backend.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Lunch Dynapps Gent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class OrderItemSchema(BaseModel):
    name: str
    quantity: int = 1
    notes: Optional[str] = None


class OrderCreate(BaseModel):
    person_name: str
    items: list[OrderItemSchema]
    amount: Optional[float] = None
    notes: Optional[str] = None


class MenuItemCreate(BaseModel):
    name: str
    category: str
    price: Optional[float] = None
    description: Optional[str] = None


class AdvancerRequest(BaseModel):
    advancer: str
    date: Optional[str] = None


class RepaidRequest(BaseModel):
    order_id: int


# ── Menu ─────────────────────────────────────────────────────────────────────

CATEGORY_ORDER = [
    "Kazen",
    "Vleeswaren",
    "Vis & schaaldieren",
    "Veggie",
    "Samengestelde broodjes",
    "Wraps",
    "Schotels",
]


@app.get("/api/menu")
def get_menu(db: Session = Depends(get_db)):
    items = db.query(MenuItem).filter(MenuItem.available == True).order_by(  # noqa: E712
        MenuItem.name
    ).all()
    return sorted(
        [
            {
                "id": i.id,
                "name": i.name,
                "category": i.category,
                "price": i.price,
                "garnish_price": i.garnish_price,
                "description": i.description,
            }
            for i in items
        ],
        key=lambda x: (
            CATEGORY_ORDER.index(x["category"]) if x["category"] in CATEGORY_ORDER else len(CATEGORY_ORDER),
            x["name"],
        ),
    )


@app.post("/api/menu/refresh")
def refresh_menu(db: Session = Depends(get_db)):
    from backend.scraper import scrape_menu
    items_data = scrape_menu()
    if not items_data:
        return {"message": "Geen items gevonden via scraping. Voeg producten handmatig toe."}
    db.query(MenuItem).delete()
    for d in items_data:
        db.add(MenuItem(
            name=d["name"], category=d["category"],
            price=d.get("price"), garnish_price=d.get("garnish_price"),
            description=d.get("description"), available=True,
        ))
    db.commit()
    return {"message": f"{len(items_data)} items geladen"}


@app.post("/api/menu/item", status_code=201)
def add_menu_item(item: MenuItemCreate, db: Session = Depends(get_db)):
    db_item = MenuItem(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return {"id": db_item.id}


@app.delete("/api/menu/item/{item_id}")
def delete_menu_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "Item niet gevonden")
    db.delete(item)
    db.commit()
    return {"message": "Item verwijderd"}


# ── Orders ────────────────────────────────────────────────────────────────────

@app.get("/api/orders")
def get_orders(order_date: Optional[str] = Query(None), db: Session = Depends(get_db)):
    target = date.fromisoformat(order_date) if order_date else date.today()
    orders = db.query(Order).filter(Order.date == target).all()
    summary = db.query(DailySummary).filter(DailySummary.date == target).first()
    return {
        "date": target.isoformat(),
        "email_sent": summary.email_sent if summary else False,
        "advancer": summary.advancer if summary else None,
        "orders": [_order_dict(o) for o in orders],
    }


@app.post("/api/orders", status_code=201)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    from backend.config import settings
    now = datetime.now()
    h, m = map(int, settings.ORDER_DEADLINE.split(":"))
    deadline = now.replace(hour=h, minute=m, second=0, microsecond=0)

    if now > deadline:
        raise HTTPException(400, f"De besteldeadline van {settings.ORDER_DEADLINE} is verstreken.")

    existing = db.query(Order).filter(
        Order.date == date.today(),
        Order.person_name == order.person_name,
    ).first()
    if existing:
        raise HTTPException(400, f"{order.person_name} heeft vandaag al een bestelling.")

    db_order = Order(
        date=date.today(),
        person_name=order.person_name,
        amount=order.amount,
        notes=order.notes,
    )
    db_order.items = [i.model_dump() for i in order.items]
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return {"id": db_order.id, "message": "Bestelling geplaatst!"}


@app.delete("/api/orders/{order_id}")
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    from backend.config import settings
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Bestelling niet gevonden")

    now = datetime.now()
    h, m = map(int, settings.ORDER_DEADLINE.split(":"))
    if now > now.replace(hour=h, minute=m, second=0, microsecond=0):
        raise HTTPException(400, "Deadline verstreken, bestelling kan niet meer worden geannuleerd.")

    db.delete(order)
    db.commit()
    return {"message": "Bestelling geannuleerd"}


# ── Betalingen ────────────────────────────────────────────────────────────────

@app.post("/api/payments/advance")
def set_advancer(req: AdvancerRequest, db: Session = Depends(get_db)):
    target = date.fromisoformat(req.date) if req.date else date.today()
    summary = db.query(DailySummary).filter(DailySummary.date == target).first()
    if not summary:
        summary = DailySummary(date=target)
        db.add(summary)
    summary.advancer = req.advancer
    db.query(Order).filter(Order.date == target).update({"advanced_by": req.advancer})
    db.commit()
    return {"message": f"{req.advancer} ingesteld als voorschietende persoon"}


@app.post("/api/payments/repaid")
def mark_repaid(req: RepaidRequest, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == req.order_id).first()
    if not order:
        raise HTTPException(404, "Bestelling niet gevonden")
    order.repaid = True
    order.repaid_at = datetime.utcnow()
    db.commit()
    return {"message": f"{order.person_name} gemarkeerd als terugbetaald"}


@app.post("/api/payments/unrepaid/{order_id}")
def mark_unrepaid(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Bestelling niet gevonden")
    order.repaid = False
    order.repaid_at = None
    db.commit()
    return {"message": f"{order.person_name} gemarkeerd als niet terugbetaald"}


@app.get("/api/balances")
def get_balances(db: Session = Depends(get_db)):
    orders = db.query(Order).filter(
        Order.advanced_by.isnot(None),
        Order.repaid == False,  # noqa: E712
    ).all()

    balances: dict = {}
    for o in orders:
        adv = o.advanced_by
        if adv not in balances:
            balances[adv] = {"advancer": adv, "debtors": [], "total_open": 0.0}
        balances[adv]["debtors"].append({
            "person": o.person_name,
            "date": o.date.isoformat(),
            "amount": o.amount,
            "order_id": o.id,
        })
        balances[adv]["total_open"] += o.amount or 0

    return list(balances.values())


# ── E-mail ────────────────────────────────────────────────────────────────────

@app.post("/api/mark-email-sent")
def mark_email_sent(order_date: Optional[str] = Query(None), db: Session = Depends(get_db)):
    target = date.fromisoformat(order_date) if order_date else date.today()
    summary = db.query(DailySummary).filter(DailySummary.date == target).first()
    if not summary:
        summary = DailySummary(date=target)
        db.add(summary)
    summary.email_sent = True
    summary.email_sent_at = datetime.utcnow()
    db.commit()
    return {"message": "E-mail gemarkeerd als verstuurd"}


@app.post("/api/reset-email-status")
def reset_email_status(order_date: Optional[str] = Query(None), db: Session = Depends(get_db)):
    target = date.fromisoformat(order_date) if order_date else date.today()
    summary = db.query(DailySummary).filter(DailySummary.date == target).first()
    if not summary:
        raise HTTPException(404, "Geen samenvatting gevonden voor deze datum")
    summary.email_sent = False
    summary.email_sent_at = None
    db.commit()
    return {"message": "E-mailstatus gereset"}


# ── Frontend ──────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin")
def serve_admin():
    return FileResponse(FRONTEND_DIR / "admin.html")


@app.get("/menu")
def serve_menu():
    return FileResponse(FRONTEND_DIR / "menu.html")


# ── Helper ────────────────────────────────────────────────────────────────────

def _order_dict(o: Order) -> dict:
    return {
        "id": o.id,
        "person_name": o.person_name,
        "items": o.items,
        "amount": o.amount,
        "notes": o.notes,
        "advanced_by": o.advanced_by,
        "repaid": o.repaid,
        "repaid_at": o.repaid_at.isoformat() if o.repaid_at else None,
        "created_at": o.created_at.isoformat(),
    }
