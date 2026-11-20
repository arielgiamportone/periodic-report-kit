# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-20

### Added

- Canonical long model and YAML-declared schema, group and item catalogues.
- Loaders: tolerant globs, draft and lock-file skipping, forbidden sheets, XML row counting,
  row-by-row group resolution, quarantine with typed warnings, local-zone timestamps, name-merge
  reporting, duplicate-control resolution and versioned parquet cache.
- Metrics: five definitions, `conformity_rate` and `clean_rate` with declared bases, breakdowns,
  qualified item rankings, totals that ignore pending cells, clean-rate lower bound.
- Chart catalogue with level, metric and a safe generation condition; document-ready tables.
- Comment store per period with drift detection; proposals are never published.
- Brand kit (palette, semantic palette, fonts with OS fallbacks, template, cover background,
  bar geometry) and the demo brand "Nordal Analytics" built by `scripts/build_brand_kit.py`.
- Word renderer: template reuse, full-bleed text cover over an anchored background, TOC field by
  outline level, letterhead on page 1, branded tables, charts, KPI rows, highlighted gaps.
- PDF renderer: two passes joined with pypdf, cover outside the numbering, CSS fallback cover,
  landscape annex.
- Markdown to docx/pptx with nine visual blocks and a demo deck.
- Report composer with versioned output and synthetic tagging; validator that contrasts a
  delivered `.docx` with the model; CLI (`generate`, `comments`, `validate`, `md`, `demo`).
- Synthetic data generator with every quirk the loader rules need.
- Project skeleton: packaging metadata, MIT license, CI (pytest on Python 3.11/3.12, ruff,
  gitleaks) and the leak-guard test with an obfuscated blocklist.
