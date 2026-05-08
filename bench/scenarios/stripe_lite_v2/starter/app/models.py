"""SQLAlchemy models for stripe_lite."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    is_admin = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan = Column(String, nullable=False)  # "free" | "pro" | "enterprise"
    seats = Column(Integer, default=1)
    monthly_price = Column(Numeric(10, 2), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)

    # NOTE: cancellation fields will be added by the agent crews.

    user = relationship("User", back_populates="subscriptions")
    invoices = relationship("Invoice", back_populates="subscription")


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    issued_at = Column(DateTime, default=datetime.utcnow)
    paid = Column(Integer, default=0)

    subscription = relationship("Subscription", back_populates="invoices")
