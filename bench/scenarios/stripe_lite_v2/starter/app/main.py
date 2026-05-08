"""FastAPI app entry point."""
from fastapi import FastAPI
from .db import init_db
from .routes import subscriptions, invoices

app = FastAPI(title="stripe_lite", version="0.1.0")
app.include_router(subscriptions.router)
app.include_router(invoices.router)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
