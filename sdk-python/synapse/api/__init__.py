"""Synapse REST API surface.

Lazy-import everything from .server so installing without the [gateway]
extras doesn't crash importing the synapse package.
"""
from __future__ import annotations


def get_app():  # pragma: no cover — thin re-export
    """Return the FastAPI app instance. Defers the import so ``import
    synapse`` doesn't require ``fastapi`` to be installed."""
    from synapse.api.server import app
    return app


__all__ = ["get_app"]
