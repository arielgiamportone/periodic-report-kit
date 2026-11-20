"""Tokens that mark what a person must still do or what cannot be computed."""

from __future__ import annotations

import re

COMMENT_TOKEN = "[[COMENTARIO]]"
PENDING_TOKEN = "[[PENDIENTE]]"
SYNTHETIC_TAG = "DATOS SINTÉTICOS"

_PLACEHOLDER = re.compile(r"\[\[[^\]]+\]\]")


def is_placeholder(value: object) -> bool:
    return isinstance(value, str) and _PLACEHOLDER.fullmatch(value.strip()) is not None


def find_placeholders(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text)
