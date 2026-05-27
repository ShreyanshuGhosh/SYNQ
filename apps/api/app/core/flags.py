"""Feature flags — environment-variable driven, no external service.

Pattern: every flag is named by its suffix; the env var is
``FEATURE_<name>`` (case-insensitive on the suffix). The value is parsed
as a boolean (true / 1 / yes / on, vs everything else = false).

API:
    from app.core.flags import flag, all_flags

    if flag("compression_v2"):
        use_v2_algorithm()

Defaults: every registered flag has an explicit default, so a fresh
install where no FEATURE_* vars are set returns False for both flags
without needing to set anything in .env.

Per the Phase 6 hard constraint: "Feature flags are read on every call,
not cached at startup. Changing an env var and restarting the API is the
only supported workflow." We deliberately do not memoize the env lookup.

Adding a new flag: append one entry to ``_REGISTRY`` and call ``flag()``
from the consumer. No other change is needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FlagDef:
    name: str
    default: bool
    description: str


# All known flags. The /api/flags endpoint reads from this registry, so a
# flag with no entry here will be invisible to the dashboard even if its
# FEATURE_ env var is set. That's intentional — surfaces drift between
# what the code uses and what the operator can see.
_REGISTRY: dict[str, FlagDef] = {
    "compression_v2": FlagDef(
        name="compression_v2",
        default=False,
        description=(
            "Use the v2 compression profile: 8-turn verbatim window "
            "(vs 15) and 12 RAG chunks (vs 8). Experiment to trade "
            "context cost for retrieval depth."
        ),
    ),
    "aggressive_rag": FlagDef(
        name="aggressive_rag",
        default=False,
        description=(
            "Also embed the rolling summary itself and retrieve chunks "
            "from it separately, merging with message-level RAG. "
            "Experimental; off by default."
        ),
    ),
}


_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "t"})


def _env_value(name: str) -> str | None:
    """Look up FEATURE_<name> in os.environ — checked on every call."""
    return os.environ.get(f"FEATURE_{name}") or os.environ.get(
        f"FEATURE_{name.upper()}"
    )


def flag(name: str) -> bool:
    """Return the current boolean value of ``name``.

    Unknown flags (not in the registry) return False so a typo in a
    consumer can't accidentally light up a code path.
    """
    if name not in _REGISTRY:
        return False
    raw = _env_value(name)
    if raw is None:
        return _REGISTRY[name].default
    return raw.strip().lower() in _TRUE_VALUES


def all_flags() -> list[dict[str, object]]:
    """Snapshot of every registered flag for the dashboard."""
    return [
        {
            "name": fd.name,
            "value": flag(fd.name),
            "default": fd.default,
            "description": fd.description,
            "env_var": f"FEATURE_{fd.name}",
        }
        for fd in _REGISTRY.values()
    ]
