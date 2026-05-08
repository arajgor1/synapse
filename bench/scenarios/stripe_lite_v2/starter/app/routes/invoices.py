"""Invoice endpoints + generation logic."""
from datetime import datetime
from decimal import Decimal
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..auth import current_user
from ..models import Invoice, Subscription, User

router = APIRouter(prefix="/invoices", tags=["invoices"])


class InvoiceOut(BaseModel):
    id: int
    subscription_id: int
    amount: float
    paid: int

    class Config:
        from_attributes = True


@router.get("/", response_model=list[InvoiceOut])
def list_my_invoices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return (
        db.query(Invoice)
        .join(Subscription, Invoice.subscription_id == Subscription.id)
        .filter(Subscription.user_id == user.id)
        .all()
    )


def generate_monthly_invoices(db: Session) -> list[Invoice]:
    """Run once per month — creates a fresh invoice per active subscription."""
    new = []
    for sub in db.query(Subscription).all():
        invoice = Invoice(
            subscription_id=sub.id,
            amount=Decimal(sub.monthly_price),
            issued_at=datetime.utcnow(),
            paid=0,
        )
        db.add(invoice)
        new.append(invoice)
    db.commit()
    return new
