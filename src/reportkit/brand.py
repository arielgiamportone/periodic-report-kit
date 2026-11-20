"""Brand kit: palette, fonts, template, cover background and cover geometry, from ``brand.yaml``.

Every colour used by a renderer comes from here. The semantic palette (ok / fail / na / warn)
is never mixed with the brand palette.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import fold, load_yaml

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True, slots=True)
class Palette:
    primary: str
    secondary: str
    ink: str
    muted: str
    accent: str
    border: str
    frame_bg: str
    page_bg: str

    def as_dict(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(frozen=True, slots=True)
class SemanticPalette:
    ok: str
    fail: str
    na: str
    warn: str

    def for_result(self, result: str) -> str:
        return {"ok": self.ok, "fail": self.fail, "na": self.na}.get(result, self.warn)


@dataclass(frozen=True, slots=True)
class FontSpec:
    name: str
    fallbacks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FontResolution:
    requested: str
    used: str
    path: Path | None  # a TTF/OTF file; None only when nothing at all was found

    @property
    def is_fallback(self) -> bool:
        return fold(self.requested) != fold(self.used)


@dataclass(frozen=True, slots=True)
class Bar:
    """A band of the cover background where variable text goes, in pixels of the PNG."""

    top: int
    height: int
    left: int
    lines: int = 1


@dataclass(frozen=True, slots=True)
class CoverGeometry:
    dpi: int
    width_px: int
    height_px: int
    bars: dict[str, Bar]
    text_color: str

    @property
    def points_per_px(self) -> float:
        return 72.0 / self.dpi

    def top_pt(self, bar: str) -> float:
        return self.bars[bar].top * self.points_per_px

    def height_pt(self, bar: str) -> float:
        return self.bars[bar].height * self.points_per_px

    def left_pt(self, bar: str) -> float:
        return self.bars[bar].left * self.points_per_px


@dataclass(slots=True)
class BrandKit:
    name: str
    palette: Palette
    semantic: SemanticPalette
    heading_font: FontSpec
    body_font: FontSpec
    font_dirs: dict[str, list[str]]
    template: Path | None
    cover_background: Path | None
    cover: CoverGeometry
    legal_footer: str
    signature: str
    synthetic_badge_color: str
    tagline: str = ""
    root: Path = field(default_factory=Path)

    @classmethod
    def load(cls, path: Path | str) -> BrandKit:
        path = Path(path)
        raw = load_yaml(path)
        root = path.parent
        pal = raw.get("palette") or {}
        sem = raw.get("semantic") or {}
        fonts = raw.get("fonts") or {}
        cover = raw.get("cover") or {}
        for key, value in {**pal, **sem}.items():
            if not HEX.match(str(value)):
                raise ValueError(f"{path}: colour {key} must be #RRGGBB, got {value!r}")

        def _font(key: str) -> FontSpec:
            spec = fonts.get(key) or {}
            return FontSpec(
                str(spec.get("name", "DejaVu Sans")), tuple(spec.get("fallbacks", ["DejaVu Sans"]))
            )

        def _asset(key: str) -> Path | None:
            value = raw.get(key)
            return (root / value) if value else None

        bars = {
            k: Bar(int(v["top"]), int(v["height"]), int(v.get("left", 0)), int(v.get("lines", 1)))
            for k, v in (cover.get("bars") or {}).items()
        }
        return cls(
            name=str(raw.get("name", "Brand")),
            palette=Palette(**{k: str(pal[k]) for k in Palette.__slots__}),
            semantic=SemanticPalette(**{k: str(sem[k]) for k in SemanticPalette.__slots__}),
            heading_font=_font("heading"),
            body_font=_font("body"),
            font_dirs={k: list(v) for k, v in (fonts.get("search_dirs") or {}).items()},
            template=_asset("template"),
            cover_background=_asset("cover_background"),
            cover=CoverGeometry(
                dpi=int(cover.get("dpi", 150)),
                width_px=int(cover.get("width_px", 1241)),
                height_px=int(cover.get("height_px", 1754)),
                bars=bars,
                text_color=str(cover.get("text_color", "#FFFFFF")),
            ),
            legal_footer=str(raw.get("legal_footer", "")),
            signature=str(raw.get("signature", "")),
            synthetic_badge_color=str(raw.get("synthetic_badge_color", "#E0A526")),
            tagline=str(raw.get("tagline", "")),
            root=root,
        )

    # -- fonts ----------------------------------------------------------------------------------

    def _search_dirs(self) -> list[Path]:
        system = platform.system().lower()
        key = {"linux": "linux", "windows": "windows", "darwin": "darwin"}.get(system, "linux")
        dirs = [
            Path(os.path.expandvars(os.path.expanduser(d))) for d in self.font_dirs.get(key, [])
        ]
        defaults = {
            "linux": [
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                "~/.fonts",
                "~/.local/share/fonts",
            ],
            "windows": [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")],
            "darwin": ["/Library/Fonts", "/System/Library/Fonts", "~/Library/Fonts"],
        }[key]
        dirs += [Path(os.path.expanduser(d)) for d in defaults]
        return [d for d in dirs if d.is_dir()]

    @staticmethod
    def _find_ttf(name: str, dirs: list[Path]) -> Path | None:
        wanted = fold(name).replace(" ", "")
        candidates: list[Path] = []
        for d in dirs:
            for p in d.rglob("*"):
                if p.suffix.lower() in {".ttf", ".otf"} and fold(p.stem).replace(" ", "").replace(
                    "-", ""
                ).startswith(wanted):
                    candidates.append(p)
        if not candidates:
            return None
        # Prefer the regular face: shortest stem wins ("DejaVuSans" before "DejaVuSans-Bold").
        return sorted(candidates, key=lambda p: (len(p.stem), str(p)))[0]

    def resolve_font(self, spec: FontSpec) -> FontResolution:
        """Find a TTF for the requested family, then each fallback, then matplotlib's DejaVu.

        The result is always a scalable font file: the bitmap default of a renderer is never
        acceptable, because it silently ignores sizes and breaks accents.
        """
        dirs = self._search_dirs()
        for name in (spec.name, *spec.fallbacks):
            path = self._find_ttf(name, dirs)
            if path is not None:
                return FontResolution(spec.name, name, path)
        try:  # matplotlib ships DejaVu Sans; it is always there when the kit is installed
            import matplotlib

            mpl_fonts = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
            path = self._find_ttf("DejaVu Sans", [mpl_fonts])
            if path is not None:
                return FontResolution(spec.name, "DejaVu Sans", path)
        except Exception:  # pragma: no cover - matplotlib missing
            pass
        return FontResolution(spec.name, spec.name, None)

    def heading(self) -> FontResolution:
        return self.resolve_font(self.heading_font)

    def body(self) -> FontResolution:
        return self.resolve_font(self.body_font)

    # -- helpers -------------------------------------------------------------------------------

    def css_variables(self) -> str:
        pal = self.palette.as_dict()
        lines = [f"--{k.replace('_', '-')}: {v};" for k, v in pal.items()]
        lines += [f"--sem-{k}: {getattr(self.semantic, k)};" for k in SemanticPalette.__slots__]
        return ":root {" + " ".join(lines) + "}"

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "template": str(self.template) if self.template else None,
            "cover_background": str(self.cover_background) if self.cover_background else None,
            "heading_font": self.heading().used,
            "body_font": self.body().used,
        }


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def mix(color: str, with_color: str, ratio: float) -> str:
    """Linear mix of two hex colours; ``ratio`` is the weight of ``with_color``."""
    a, b = hex_to_rgb(color), hex_to_rgb(with_color)
    out = tuple(round(a[i] * (1 - ratio) + b[i] * ratio) for i in range(3))
    return "#{:02X}{:02X}{:02X}".format(*out)
