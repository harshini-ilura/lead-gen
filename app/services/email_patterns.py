"""Phase 4 — email pattern generation.

Generates likely email addresses from a person's name + company domain. Where the
company's pattern can be INFERRED from real emails already found (Phase 3), we
apply that exact pattern (high confidence); otherwise we fall back to a ranked set
of common corporate patterns (low confidence) for Phase 5 to verify.
"""
import re
import unicodedata
from typing import Callable, Optional

# Each pattern: name -> (first, last) -> local-part. `last` may be "".
_PATTERNS: dict[str, Callable[[str, str], Optional[str]]] = {
    "first": lambda f, l: f or None,
    "first.last": lambda f, l: f"{f}.{l}" if f and l else None,
    "firstlast": lambda f, l: f"{f}{l}" if f and l else None,
    "flast": lambda f, l: f"{f[0]}{l}" if f and l else None,
    "f.last": lambda f, l: f"{f[0]}.{l}" if f and l else None,
    "first.l": lambda f, l: f"{f}.{l[0]}" if f and l else None,
    "firstl": lambda f, l: f"{f}{l[0]}" if f and l else None,
    "last.first": lambda f, l: f"{l}.{f}" if f and l else None,
    "lastfirst": lambda f, l: f"{l}{f}" if f and l else None,
}

# Fallback order when the company pattern is unknown (most common first).
DEFAULT_PATTERNS = ["first", "first.last", "flast", "firstlast"]


def _slug(name: Optional[str]) -> str:
    """Lowercase ASCII, letters only — 'O'Neill' -> 'oneill', 'Ford-Robertson' -> 'fordrobertson'."""
    if not name:
        return ""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_name.lower())


def infer_company_patterns(known: list[tuple[str, str, str]]) -> list[str]:
    """known = [(first_name, last_name, email_local_part), ...] from real emails.

    Returns the company's pattern names ordered by how often they explain the
    known local-parts (most common first).
    """
    counts: dict[str, int] = {}
    for first, last, local in known:
        f, l, lp = _slug(first), _slug(last), (local or "").lower()
        if not f or not lp:
            continue
        for name, fn in _PATTERNS.items():
            produced = fn(f, l)
            if produced and produced == lp:
                counts[name] = counts.get(name, 0) + 1
                break  # first (highest-priority) matching pattern wins
    return sorted(counts, key=lambda n: counts[n], reverse=True)


def generate(
    first: Optional[str], last: Optional[str], domain: str, patterns: list[str]
) -> list[tuple[str, str]]:
    """Return [(email, pattern_name), ...] for the given patterns (de-duplicated)."""
    f, l = _slug(first), _slug(last)
    if not f or not domain:
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in patterns:
        fn = _PATTERNS.get(name)
        if not fn:
            continue
        local = fn(f, l)
        if not local:
            continue
        email = f"{local}@{domain}".lower()
        if email not in seen:
            seen.add(email)
            out.append((email, name))
    return out
