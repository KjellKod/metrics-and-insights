from __future__ import annotations


def _token(*parts: str) -> str:
    return "".join(parts)


BLOCKED_IDENTIFIER_TOKENS = (
    "2025 vs 2026",
    _token("on", "fleet"),
    _token("Sp", "ork"),
    _token("Pa", "nda"),
    _token("Mi", "nt"),
    _token("Black", "widow"),
    _token("rod", "olfo"),
    _token("Gon", "zalo"),
    _token("Nas", "tassy"),
)

