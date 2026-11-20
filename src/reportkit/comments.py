"""Human comments: a YAML store per period and section.

The system writes the mechanical part (figures, methodology, tables) and leaves a
``[[COMENTARIO]]`` gap with the current figures ("hints") next to it. A stored comment is
published; if its hints differ from the current ones the kit warns about drift. A
``proposal`` field (an automatic draft) is never published without passing through a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .model import Warning
from .placeholders import COMMENT_TOKEN


@dataclass(frozen=True, slots=True)
class Comment:
    section: str
    text: str | None
    hints: dict[str, Any] = field(default_factory=dict)
    proposal: str | None = None

    @property
    def is_filled(self) -> bool:
        return bool(self.text and self.text.strip())


def format_hints(hints: dict[str, Any]) -> str:
    parts = []
    for k, v in hints.items():
        if isinstance(v, float):
            parts.append(f"{k}={v:.3g}")
        else:
            parts.append(f"{k}={v}")
    return "; ".join(parts)


@dataclass(slots=True)
class CommentStore:
    period: str
    path: Path
    entries: dict[str, Comment] = field(default_factory=dict)

    @classmethod
    def load(cls, period: str, directory: Path | str) -> CommentStore:
        path = Path(directory) / f"{period}.yaml"
        store = cls(period=period, path=path)
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            for section, body in (raw.get("sections") or {}).items():
                body = body or {}
                store.entries[str(section)] = Comment(
                    section=str(section),
                    text=body.get("text"),
                    hints=dict(body.get("hints") or {}),
                    proposal=body.get("proposal"),
                )
        return store

    def get(self, section: str) -> Comment:
        return self.entries.get(section, Comment(section=section, text=None))

    def render(self, section: str, current_hints: dict[str, Any]) -> tuple[str, list[Warning]]:
        """Text to publish for a section plus drift warnings. Never the proposal."""
        warnings: list[Warning] = []
        c = self.get(section)
        if not c.is_filled:
            return f"{COMMENT_TOKEN} {format_hints(current_hints)}", warnings
        if c.hints and _differs(c.hints, current_hints):
            warnings.append(
                Warning(
                    "comment-stale",
                    f"comment for {section!r} was written with other figures: {format_hints(c.hints)} vs {format_hints(current_hints)}",
                    details={"section": section, "stored": c.hints, "current": current_hints},
                )
            )
        assert c.text is not None
        return c.text.strip(), warnings

    def write_template(
        self, hints_by_section: dict[str, dict[str, Any]], overwrite: bool = False
    ) -> Path:
        """Write (or complete) the YAML with a gap and the current hints for every section."""
        existing = self.entries if not overwrite else {}
        sections: dict[str, Any] = {}
        for section, hints in hints_by_section.items():
            prev = existing.get(section)
            sections[section] = {
                "text": prev.text if prev and prev.text else None,
                "hints": _plain(hints),
                "proposal": prev.proposal if prev else None,
            }
        for section, prev in existing.items():
            sections.setdefault(
                section, {"text": prev.text, "hints": _plain(prev.hints), "proposal": prev.proposal}
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            fh.write(
                f"# Comentarios del periodo {self.period}. Rellena 'text'; 'hints' son las cifras con las que se escribió.\n"
            )
            fh.write(
                "# 'proposal' es un borrador automático: NUNCA se publica sin pasar a 'text' a mano.\n"
            )
            yaml.safe_dump(
                {"period": self.period, "sections": sections},
                fh,
                allow_unicode=True,
                sort_keys=False,
            )
        return self.path


def _plain(hints: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in hints.items():
        if hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float):
            v = round(v, 4)
        out[k] = v
    return out


def _differs(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    for k, v in stored.items():
        if k not in current:
            return True
        cv = current[k]
        if isinstance(v, int | float) and isinstance(cv, int | float):
            if abs(float(v) - float(cv)) > 1e-3:
                return True
        elif str(v) != str(cv):
            return True
    return False
