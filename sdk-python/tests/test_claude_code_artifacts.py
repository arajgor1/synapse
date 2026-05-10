"""Smoke tests for the Claude Code skills + sub-agent shipped under
launch/claude-code-{skills,agents}/.

Verifies:

  * Each skill file has valid YAML frontmatter with `name` + `description`.
  * Each skill references real Synapse v0.2.3 entry points.
  * The synapse-coordinator agent has frontmatter + meaningful body.
  * Cross-references between skills are consistent (no broken slugs).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "launch" / "claude-code-skills"
AGENTS_DIR = REPO_ROOT / "launch" / "claude-code-agents"


EXPECTED_SKILLS = (
    "synapse-audit", "synapse-watch", "synapse-intend",
    "synapse-resolve-conflict", "synapse-explain",
)


def _has_artifacts() -> bool:
    return SKILLS_DIR.is_dir() and AGENTS_DIR.is_dir()


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML frontmatter extractor — no external deps."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end].strip()
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


@pytest.mark.skipif(not _has_artifacts(), reason="claude-code artifacts missing")
def test_all_five_skills_present():
    for slug in EXPECTED_SKILLS:
        path = SKILLS_DIR / slug / "SKILL.md"
        assert path.exists(), f"missing skill: {path}"


@pytest.mark.skipif(not _has_artifacts(), reason="claude-code artifacts missing")
@pytest.mark.parametrize("slug", EXPECTED_SKILLS)
def test_skill_frontmatter_valid(slug: str):
    text = (SKILLS_DIR / slug / "SKILL.md").read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert fm.get("name") == slug, (
        f"frontmatter name {fm.get('name')!r} != slug {slug!r}"
    )
    assert fm.get("description"), f"{slug} missing description in frontmatter"
    # Description should be substantive (not just the slug)
    assert len(fm["description"]) > 40, (
        f"{slug} description too short -- Claude Code uses it for trigger detection"
    )


@pytest.mark.skipif(not _has_artifacts(), reason="claude-code artifacts missing")
@pytest.mark.parametrize("slug", EXPECTED_SKILLS)
def test_skill_references_real_synapse_entry_point(slug: str):
    """Every skill must reference at least one current Synapse v0.2.3
    entry point so the LLM gets a runnable command, not stale doc."""
    text = (SKILLS_DIR / slug / "SKILL.md").read_text(encoding="utf-8").lower()
    keywords = (
        "synapse audit", "synapse watch", "synapse api", "synapse-mcp",
        "synapse.install", "synapse.intend", "synapse.with_agent",
        "synapse.mergepolicy", "synapse.merge_policy",
        "scope_inference", "is_write",
    )
    assert any(k in text for k in keywords), (
        f"{slug} doesn't mention any Synapse entry point -- stale doc."
    )


@pytest.mark.skipif(not _has_artifacts(), reason="claude-code artifacts missing")
def test_synapse_coordinator_agent_present_and_well_formed():
    path = AGENTS_DIR / "synapse-coordinator.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    assert fm.get("name") == "synapse-coordinator"
    desc = fm.get("description", "")
    # Description must mention the coordination domain so Claude Code
    # routes the right questions to this agent.
    assert "coordination" in desc.lower() or "multi-agent" in desc.lower()
    # Body should reference the canonical 12-framework + 10-policy surface
    body = text[text.find("\n---", 3) + 4:].lower()
    for term in ("queue_behind", "redirect", "auto_merge",
                 "langgraph", "crewai", "synapse.with_agent"):
        assert term in body, (
            f"synapse-coordinator agent body doesn't reference {term!r} -- "
            f"it lacks the canonical surface and might mislead users."
        )


@pytest.mark.skipif(not _has_artifacts(), reason="claude-code artifacts missing")
def test_skill_cross_references_resolve():
    """Skills reference each other via /skill-name links. Every link
    target must exist as a sibling skill."""
    bad = []
    pattern = re.compile(r"`/(synapse-[a-z-]+)`")
    for slug in EXPECTED_SKILLS:
        text = (SKILLS_DIR / slug / "SKILL.md").read_text(encoding="utf-8")
        for ref in pattern.findall(text):
            if ref not in EXPECTED_SKILLS and ref != slug:
                # Allow refs to skills we know don't exist YET (e.g.
                # /synapse-install-framework is referenced but not
                # shipped — that's a documented future skill).
                if ref in ("synapse-install-framework",):
                    continue
                bad.append((slug, ref))
    assert not bad, f"broken cross-refs: {bad}"
