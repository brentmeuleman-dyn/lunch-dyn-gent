import json
from datetime import date, datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text
from backend.database import Base


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    category = Column(String(100), nullable=False)
    price = Column(Float, nullable=True)
    garnish_price = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    available = Column(Boolean, default=True)
    last_scraped = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, default=date.today, index=True)
    person_name = Column(String(100), nullable=False)
    _items = Column("items", Text, nullable=False, default="[]")
    amount = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    advanced_by = Column(String(100), nullable=True)
    repaid = Column(Boolean, default=False)
    repaid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def items(self):
        return json.loads(self._items)

    @items.setter
    def items(self, value):
        self._items = json.dumps(value, ensure_ascii=False)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, default=date.today, index=True)
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime, nullable=True)
    advancer = Column(String(100), nullable=True)
