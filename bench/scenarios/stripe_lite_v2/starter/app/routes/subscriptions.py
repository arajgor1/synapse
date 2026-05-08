"""Subscription endpoints — list + create. Cancel/restore/status added by crews."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..db import get_db
from ..auth import current_user
from ..models import Subscription, User

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

PLAN_PRICES = {"free": 0, "pro": 29, "enterprise": 199}


class CreateSubscriptionIn(BaseModel):
    plan: str
    seats: int = 1


class SubscriptionOut(BaseModel):
    id: int
    user_id: int
    plan: str
    seats: int
    monthly_price: float

    class Config:
        from_attributes = True


@router.get("/", response_model=list[SubscriptionOut])
def list_my_subs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Subscription).filter(Subscription.user_id == user.id).all()


@router.post("/", response_model=SubscriptionOut)
def create_sub(payload: CreateSubscriptionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail=f"unknown plan: {payload.plan}")
    sub = Subscription(
        user_id=user.id,
        plan=payload.plan,
        seats=payload.seats,
        monthly_price=PLAN_PRICES[payload.plan] * payload.seats,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub
