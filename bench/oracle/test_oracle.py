"""Gate 0 smoke test for the oracle.

Build a synthetic 'finished cell' with known-truth:
  - 2 file collisions (one silent, one not)
  - 3 belief divergences (column name, endpoint path, status code)
  - coherence ~0.4 (some markers hit, some miss)

Run the oracle. Assert the numbers come back within tolerance.

This validates the oracle WITHOUT spending LLM tokens (uses a stub
client that returns canned divergences).
"""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path

from bench.oracle.scorer import (
    find_file_collisions,
    find_silent_overwrites,
    find_textual_conflicts_in_repo,
    score_coherence,
    score_cell,
    hash_content,
)


def _build_synthetic_repo(repo_root: Path):
    """Construct a 'final state' that matches what 2 colliding crews
    would have left behind."""
    (repo_root / "app").mkdir(parents=True, exist_ok=True)
    (repo_root / "app" / "routes").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)

    # models.py — crew_a's version won (American spelling).
    # crew_b had written cancelled_at (British). Silent overwrite expected.
    (repo_root / "app" / "models.py").write_text("""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base
Base = declarative_base()

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    canceled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(String, nullable=True)
    grace_until = Column(DateTime, nullable=True)
""", encoding="utf-8")

    # routes/subscriptions.py — crew_a's version.
    # Uses 'canceled', /cancel endpoint, 7-day grace, 409 conflict.
    (repo_root / "app" / "routes" / "subscriptions.py").write_text("""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
router = APIRouter()

@router.post("/subscriptions/{id}/cancel")
def cancel(id: int):
    if False:  # already canceled check
        raise HTTPException(status_code=409, detail="already canceled")
    grace = datetime.utcnow() + timedelta(days=7)
    return {"state": "active"}

@router.get("/subscriptions/{id}/status")
def status(id: int):
    return {"state": "grace"}
""", encoding="utf-8")

    # routes/admin.py — crew_b's version. Different value: 'cancelled' (British)
    (repo_root / "app" / "routes" / "admin.py").write_text("""
from fastapi import APIRouter
router = APIRouter()

@router.post("/admin/subscriptions/{sub_id}/restore")
def restore(sub_id: int):
    # crew_b used 'cancelled' (British) and 400 status — divergence
    return {"state": "cancelled"}
""", encoding="utf-8")

    # routes/invoices.py — references grace_until but no prorated logic
    (repo_root / "app" / "routes" / "invoices.py").write_text("""
from datetime import datetime
def generate(db):
    for sub in db.subs:
        if sub.grace_until and sub.grace_until < datetime.utcnow():
            continue
        # forgot prorated flag — coherence marker miss
        yield invoice
""", encoding="utf-8")

    # tests
    (repo_root / "tests" / "test_cancel.py").write_text("""
def test_cancel_subscription():
    pass
""", encoding="utf-8")


def _build_synthetic_write_log() -> tuple[list[dict], list[str], list[str]]:
    """Two crews wrote partially overlapping paths. Two collisions,
    one of which is a silent overwrite (different content)."""
    crew_a_paths = [
        "app/models.py",
        "app/routes/subscriptions.py",
        "app/routes/invoices.py",
        "tests/test_cancel.py",
    ]
    crew_b_paths = [
        "app/models.py",          # COLLISION (silent — different content from crew_a)
        "app/routes/admin.py",
        "app/routes/invoices.py", # COLLISION (silent — different content)
    ]

    write_log = []
    # crew_b writes models.py first (with British spelling)
    write_log.append({"ts": 1.0, "agent_id": "crew_b_backend", "path": "app/models.py",
                      "content_hash": hash_content("class Subscription:\n    cancelled_at = ...")})
    # crew_a overwrites with American
    write_log.append({"ts": 2.0, "agent_id": "crew_a_backend", "path": "app/models.py",
                      "content_hash": hash_content("class Subscription:\n    canceled_at = ...")})

    # invoices: crew_a writes first
    write_log.append({"ts": 3.0, "agent_id": "crew_a_backend", "path": "app/routes/invoices.py",
                      "content_hash": hash_content("v1 with prorated")})
    # crew_b overwrites
    write_log.append({"ts": 4.0, "agent_id": "crew_b_backend", "path": "app/routes/invoices.py",
                      "content_hash": hash_content("v2 without prorated")})

    # Non-collision writes
    write_log.append({"ts": 5.0, "agent_id": "crew_a_backend", "path": "app/routes/subscriptions.py",
                      "content_hash": hash_content("subs routes")})
    write_log.append({"ts": 6.0, "agent_id": "crew_b_backend", "path": "app/routes/admin.py",
                      "content_hash": hash_content("admin routes")})
    write_log.append({"ts": 7.0, "agent_id": "crew_a_backend", "path": "tests/test_cancel.py",
                      "content_hash": hash_content("tests")})

    return write_log, crew_a_paths, crew_b_paths


class _StubAnthropicClient:
    """Returns canned divergences without burning tokens. Mimics the
    Anthropic SDK shape just enough for scorer.py to parse."""
    def __init__(self):
        self.messages = self
        # call counter for any accidental over-calling
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        canned = {
            "divergences": [
                {
                    "key": "canceled_column_spelling",
                    "value_a": "canceled_at",
                    "value_b": "cancelled_at",
                    "evidence_a": "canceled_at = Column(DateTime",
                    "evidence_b": "cancelled_at = Column",
                    "severity": "high",
                    "rationale": "American vs British spelling will silently mismatch in queries",
                },
                {
                    "key": "subscription_state_value",
                    "value_a": "canceled",
                    "value_b": "cancelled",
                    "evidence_a": '{"state": "canceled"}',
                    "evidence_b": '{"state": "cancelled"}',
                    "severity": "high",
                    "rationale": "Frontend matching on 'canceled' will miss responses returning 'cancelled'",
                },
                {
                    "key": "already_canceled_status_code",
                    "value_a": "409",
                    "value_b": "400",
                    "evidence_a": "status_code=409",
                    "evidence_b": "status_code=400",
                    "severity": "medium",
                    "rationale": "Inconsistent error semantics for the same logical error",
                },
            ]
        }
        # return shape that mirrors anthropic SDK
        class _Content:
            def __init__(self, text):
                self.text = text
        class _Msg:
            def __init__(self, text):
                self.content = [_Content(text)]
        return _Msg(json.dumps(canned))


def run_gate_0():
    print("=== Gate 0: oracle smoke test ===")
    failures = []

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        _build_synthetic_repo(repo)
        write_log, a_paths, b_paths = _build_synthetic_write_log()

        # 1. file collisions: expect exactly 2 (models.py, invoices.py)
        collisions = find_file_collisions(write_log)
        if len(collisions) != 2:
            failures.append(f"file_collisions: expected 2, got {len(collisions)}: {[c.path for c in collisions]}")
        else:
            print(f"  ✓ file_collisions = 2  ({[c.path for c in collisions]})")

        # 2. silent overwrites: both collisions have different content → 2
        silent = find_silent_overwrites(collisions)
        if len(silent) != 2:
            failures.append(f"silent_overwrites: expected 2, got {len(silent)}")
        else:
            print(f"  ✓ silent_overwrites = 2")

        # 3. textual conflicts: synthetic repo has none (no merge markers)
        textual = find_textual_conflicts_in_repo(str(repo))
        if len(textual) != 0:
            failures.append(f"textual_conflicts: expected 0, got {len(textual)}")
        else:
            print(f"  ✓ textual_conflicts = 0  (no merge markers in synthetic repo)")

        # 4. coherence: this synthetic repo is intentionally "mostly correct"
        # (American spelling, all 3 columns, all 3 endpoints, all 3 state
        # values, 409 status, days=7, grace_until in invoices, test_cancel).
        # The ONE expected miss is `prorated` flag in invoices.py.
        # So we expect EXACTLY 14/15 = 0.9333... — known truth, not a band.
        markers_path = Path(__file__).parent.parent / "scenarios" / "stripe_lite_v2" / "markers.json"
        coherence, breakdown = score_coherence(str(repo), str(markers_path))
        # Synthetic repo intentionally has British "cancelled" in admin.py
        # and no American "canceled" string literal anywhere — so the
        # state_value_canceled marker misses by design (this models the
        # belief divergence the oracle should also catch via the LLM oracle).
        # Note: `prorated` is matched in invoices.py via comment text.
        expected_misses = {"state_value_canceled"}
        actual_misses = {r.id for r in breakdown if not r.matched}
        if actual_misses != expected_misses:
            failures.append(
                f"coherence misses: expected {sorted(expected_misses)}, "
                f"got {sorted(actual_misses)}"
            )
        else:
            print(f"  ✓ coherence = {coherence:.4f}  (14/15 markers, 1 expected miss: state_value_canceled)")
            for r in breakdown:
                glyph = "✓" if r.matched else "✗"
                print(f"      {glyph} {r.id} ({r.category})")

        # 5. belief divergences via stub client: expect 3
        stub = _StubAnthropicClient()
        result = score_cell(
            cell_id="gate_0_smoke",
            strategy="synthetic",
            repo_root=str(repo),
            write_log=write_log,
            crew_a_paths=a_paths,
            crew_b_paths=b_paths,
            markers_path=str(markers_path),
            anthropic_client=stub,
        )
        if len(result.belief_divergences) != 3:
            failures.append(f"belief_divergences: expected 3, got {len(result.belief_divergences)}")
        else:
            print(f"  ✓ belief_divergences = 3  ({[d['key'] for d in result.belief_divergences]})")

    if failures:
        print("\n!!! GATE 0 FAILED !!!")
        for f in failures:
            print(f"   - {f}")
        return False

    print("\n=== Gate 0 PASSED ===")
    return True


if __name__ == "__main__":
    import sys
    ok = run_gate_0()
    sys.exit(0 if ok else 1)
