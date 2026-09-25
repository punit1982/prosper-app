"""
The one declaration of which analysis framework is current.

Every page that reads `prosper_analysis` filters on this, so a verdict produced by a retired
framework (GROW v5.1, or the PROSPER v3.0 engine before it) is never shown as if it were a
current one. PROSPER v5.13.1 P9: "A different framework's levels (GROW, TRIAD, v8+) are not a
prior run. Name them for context only."

Kept in its own module, with no imports, so core/database.py can use it without pulling in the
engine (and the engine's anthropic import) at page load.
"""

FRAMEWORK_VERSION = "PROSPER v5.13.1"
FRAMEWORK_SHORT = "PROSPER"


def is_current(framework) -> bool:
    """True only for rows written by the current framework."""
    return str(framework or "").strip() == FRAMEWORK_VERSION


def retired_label(framework) -> str:
    """Plain name of the framework that wrote a superseded row."""
    f = str(framework or "").strip()
    if f.startswith("GROW"):
        return f
    if f.startswith("PROSPER"):
        return f
    return "the retired PROSPER v3.0 engine"
