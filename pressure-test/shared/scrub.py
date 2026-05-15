"""Text scrubber: two passes.

  Pass 1 — Prompt-injection detection
    Detects adversarial instructions embedded in input text intended to
    manipulate an LLM downstream. Strips them and returns:
      - the cleaned text
      - a list of detected attacks (each with span + type + the matched
        snippet) for the audit trail.

  Pass 2 — AI-fingerprint launder (optional)
    Replaces common AI-output fingerprints (em-dashes, certain emoji,
    overused phrases) with more neutral substitutes. Operates only on
    OUTPUT we're about to generate-then-send.

  Both passes log a POLICY envelope via the caller's Synapse session so
  every transformation is auditable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Pass 1: prompt-injection detection
# ---------------------------------------------------------------------------

# Regex patterns ranked by severity. Each fires a separate detection event.
INJECTION_PATTERNS: List[Tuple[str, str, str]] = [
    # (name, severity, regex)
    (
        "ignore_previous",
        "high",
        r"(?i)\b(ignore|disregard|forget)\s+(the\s+)?(previous|prior|all|any)\s+(instructions?|prompts?|rules?)\b",
    ),
    (
        "ai_instruction_marker",
        "high",
        r"(?i)\bif\s+you\s+are\s+(an?\s+)?(ai|llm|gpt|bot|assistant|language\s+model)\b[^.]*",
    ),
    (
        "hidden_instruction_marker",
        "high",
        r"(?i)\bhidden\s+instructions?\s+(for|to)\s+(any\s+)?(ai|llm|gpt|bot|assistant|screening\s+tool)\b[^.]*",
    ),
    (
        "include_secret_phrase",
        "medium",
        r"(?i)\b(include|insert|add|append|put)\s+(the\s+)?(phrase|word|line|text|string)\s+['\"][^'\"\n]{1,80}['\"]",
    ),
    (
        "output_recipe",
        "medium",
        r"(?i)\b(output|generate|produce|write|send|reply\s+with)\s+(a\s+)?(recipe|poem|story|joke|haiku|song)\b",
    ),
    (
        "human_only_check",
        "low",
        r"(?i)\b(only\s+humans?|to\s+prove\s+you\s+are\s+human|to\s+show\s+you\s+are\s+human)\b[^.]*",
    ),
]


@dataclass
class Detection:
    pattern: str
    severity: str
    span: Tuple[int, int]
    matched: str


@dataclass
class ScrubResult:
    original_text: str
    cleaned_text: str
    detections: List[Detection] = field(default_factory=list)
    fingerprints_replaced: int = 0

    @property
    def had_injection(self) -> bool:
        return len(self.detections) > 0


def detect_prompt_injection(text: str) -> List[Detection]:
    """Find all prompt-injection patterns in `text`."""
    detections: List[Detection] = []
    for name, severity, pattern in INJECTION_PATTERNS:
        for m in re.finditer(pattern, text):
            detections.append(
                Detection(
                    pattern=name,
                    severity=severity,
                    span=(m.start(), m.end()),
                    matched=m.group(0)[:120],
                )
            )
    return detections


def strip_injection_payloads(text: str, detections: List[Detection]) -> str:
    """Return `text` with detected injection spans removed.

    Replaces each span with a redaction marker so the cleaned text stays
    a valid passage. Operates on overlapping spans by collapsing them.
    """
    if not detections:
        return text
    # Sort + merge overlapping spans
    spans = sorted(d.span for d in detections)
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out: List[str] = []
    cursor = 0
    for s, e in merged:
        out.append(text[cursor:s])
        out.append("[REDACTED: prompt-injection]")
        cursor = e
    out.append(text[cursor:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Pass 2: AI-fingerprint launder (optional)
# ---------------------------------------------------------------------------

# Mapping of AI-fingerprint patterns to neutral substitutes. Optional —
# we POLICY-log every replacement so the audit trail is honest.
FINGERPRINT_SUBSTITUTIONS: List[Tuple[str, str]] = [
    # em-dash typical of LLM output → space-hyphen-space
    ("—", " - "),
    # en-dash too (similar fingerprint)
    ("–", " - "),
    # smart quotes → straight quotes
    ("“", '"'),
    ("”", '"'),
    ("‘", "'"),
    ("’", "'"),
    # specific overused LLM phrases (verbatim replacements)
    (" delve into ", " explore "),
    (" tapestry of ", " set of "),
    (" leverage ", " use "),
    (" furthermore, ", " also, "),
]

# Emojis fingerprinting is harder; we just strip a small set known to
# appear in AI output. Conservative.
EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001F9FF\U0001FA00-\U0001FAFF☀-⛿✀-➿]"
)


def launder_ai_fingerprints(text: str) -> Tuple[str, int]:
    """Return `(laundered_text, n_replacements_made)`.

    POLICY note: this transformation is OPT-IN by the caller. Every call
    is intended to be logged via a Synapse POLICY-style audit event by
    the caller, so the audit trail records exactly what was changed.
    """
    n = 0
    out = text
    for needle, repl in FINGERPRINT_SUBSTITUTIONS:
        before = out
        out = out.replace(needle, repl)
        if out != before:
            n += before.count(needle)
    # Strip emojis (count first)
    emoji_count = len(EMOJI_PATTERN.findall(out))
    out = EMOJI_PATTERN.sub("", out)
    n += emoji_count
    return out, n


# ---------------------------------------------------------------------------
# Convenience: full-pass scrubber
# ---------------------------------------------------------------------------
def scrub(text: str, *, launder_fingerprints: bool = False) -> ScrubResult:
    """One-call pass: detect injections, strip them, optionally launder."""
    detections = detect_prompt_injection(text)
    cleaned = strip_injection_payloads(text, detections)
    replaced = 0
    if launder_fingerprints:
        cleaned, replaced = launder_ai_fingerprints(cleaned)
    return ScrubResult(
        original_text=text,
        cleaned_text=cleaned,
        detections=detections,
        fingerprints_replaced=replaced,
    )
