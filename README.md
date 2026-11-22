# periodic-report-kit

[Versión en español](https://github.com/arielgiamportone/periodic-report-kit/blob/main/README.es.md)

Declarative periodic reports: tabular data in, branded Word / PDF / PPTX out, with a full-bleed
cover, a real table-of-contents field, conditional charts and gaps for human comments. A
clean-room case study built from a written specification, with synthetic data only.

[![CI](https://github.com/arielgiamportone/periodic-report-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/arielgiamportone/periodic-report-kit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/periodic-report-kit.svg)](https://pypi.org/project/periodic-report-kit/)
![Python 3.11 | 3.12](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

Install: `pip install periodic-report-kit` (the importable package and the CLI are `reportkit`).

## The problem

In recurring inspection or audit services the periodic report is assembled by hand: someone
exports spreadsheets from the field system, recomputes totals in pivot tables, pastes figures
and charts into a Word file with a letterhead and rebuilds the cover every month. The process
costs hours, the figures in the summary contradict the chapters, and regenerating the document
destroys the comments a person had already written.

## Constraints

- Input is whatever the field system exports: Excel or CSV, inconsistent folder and file names,
  hand-made summary sheets next to the raw sheet, drafts and lock files in the same folder.
- The output must carry the client's letterhead, a selectable cover, an index that Word updates,
  and a PDF with the cover outside the page numbering.
- It has to run on Linux servers and in CI without Office installed.
- Every percentage must declare its base, nothing may be silently read as zero, and a comment
  written by a person must survive regeneration.
- Public repository: no real data, no client names, no internal paths. Everything in the tests
  and the demo is generated.

## Architecture

```
 raw Excel / CSV
      │  loaders: translate, never interpret; unknown rows -> quarantine + typed warning
      ▼
 ╔═ CANONICAL MODEL ═════════════════════════════════════════════════╗
 ║ one long DataFrame, one row per evaluated item                      ║
 ║ period · group · control · element · dims… · category · item ·      ║
 ║ result ∈ {ok, fail, na} · comment · timestamp · source · unit       ║
 ║ ← boundary: above this line nobody knows which file a row came from ║
 ╚═════════════════════════════════╤═════════════════════════════════╝
                                   ▼
 metrics: five definitions, two rates with fixed names, cuts by any dimension
      │                     │                      │
      ▼                     ▼                      ▼
 charts (matplotlib)     tables              human comments (YAML per period)
 declare level, metric   document-ready      a gap with hints when there is no text
 and a condition
      └──────────────┬───────────┴──────────────────┘
                     ▼
 composition: sections per report type (monthly / semester / annual) from a catalogue
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
 Word render     PDF render     Markdown -> docx / pptx
 template +      two passes +   nine visual blocks
 brand kit       pypdf merge    + brand kit
                     │
                     ▼
 validator: contrast with the delivered file, exit 1 on any discrepancy
```

Configuration files, not code, hold the rules:

| File | Governs |
|---|---|
| `data/config/data_schema.yaml` | raw column names with accepted variants, valid and forbidden sheets, raw result values, local time zone, tolerant file globs |
| `data/config/groups.yaml` | report groups (chapters), label variants, responsible dimension, element reassignments, reason when a group has no source |
| `data/config/items.yaml` | raw category -> canonical (accents, case, numeric prefixes), explicit merges, symptoms of a shifted column |
| `data/config/report_catalog.yaml` | sections per report type, charts with their condition (`if: incidents >= 3`), periods on the axis, fixed texts |
| `data/brands/<brand>/brand.yaml` | palette, semantic palette, fonts with fallbacks, template, cover background, bar geometry, legal footer |

Package layout: `src/reportkit/{schema,model,loaders,metrics,charts,tables,comments,brand,catalog,
report,render_docx,render_pdf,render_md,validator,synthetic,defaults,cli}.py`. The default
configuration and the demo brand ship inside the package under `src/reportkit/data/` and are
resolved with `importlib.resources`, so the installed wheel works from any directory;
`reportkit paths` prints where they live so you can copy them and pass `--config` / `--brand`.

## Domain rules (each one has a test)

1. **The date range is an explicit parameter** (`--from 2026-01 --to 2026-06`). It is never
   deduced from folder names or the calendar; a half-year may cross the year boundary.
2. **A row without a result is not an evaluated item**; counting it inflates the denominator.
   The loader reports how many rows it dropped and which controls they belonged to.
3. **Hand-made sheets are never read.** Everything is recomputed from the raw sheet; forbidden
   sheet names are declared in the schema.
4. **Tolerant globs**: folders with or without accents, singular or plural, `03.` or `3.`; the
   history is never renamed. Duplicates are removed by resolved path.
5. **Every percentage declares its base.** Two confusable rates carry fixed names:
   `conformity_rate` = ok / (ok + fail) over items and `clean_rate` = clean controls / controls.
   The variant with "not applicable" in the denominator is deliberately absent.
6. **Sum volume, average only what is comparable.** Total actions add every unit (controls,
   surveys…); rates and densities use only controls of the same unit.
7. **Clean-case rate on aggregated sources is a lower bound over total visits**, a base that
   exists in the client's own files, instead of a restricted base that fabricates a trend.
8. **Timestamps are converted to the declared local zone before the period is derived.** A UTC
   export at 23:30Z on the 1st lands on the 2nd.
9. **Name normalisation only fixes whitespace** (repeated, hard, before a comma) and reports
   every merge; different concepts are never merged unless listed explicitly.
10. **The human comment is a gap, not generated text.** `[[COMENTARIO]]` plus the current
    figures; a stored comment is published and drift between its figures and the current ones is
    reported. An automatic proposal is never published.
11. **What cannot be computed is `[[PENDIENTE]]`**, never zero; totals ignore it.
12. **Two grouping levels that never mix**: category (breakdowns) and item (top-N); an item name
    repeated across categories is qualified "item (category)".
13. **Deliverables are never overwritten**: every run writes to `out/<type>_<from>_<to>/vNNN/`,
    and a period counts as delivered only when it has a PDF.
14. **The declared sheet dimension is not trusted**: rows are counted in the sheet XML and
    transient I/O errors are retried before concluding "empty".

## Decisions and discarded alternatives

| Decision | Discarded | Why |
|---|---|---|
| HTML -> PDF in two passes joined with pypdf | named `@page` rules in one HTML | the target engine ignores them; a zero-margin cover and a numbered body cannot share a page template |
| python-docx plus surgical XML | automating Word through COM | must run on Linux and in CI without Office; COM is fragile and not reproducible |
| TOC field by outline level (`\o "1-2"`), level set on the paragraph | TOC by style name | the style switch uses a separator that changes with Word's language and fails as an empty index; on the paragraph, the "Contents" title stays out of its own index |
| Cover as Word text over a background anchored behind the text at 0,0 | a full PNG composed with Pillow | text was not selectable and a missing font fell back to a bitmap without warning; the PNG survives only for the PDF |
| Rules in YAML with tests | `if` in the code | a criterion that changes must be a line in a catalogue, not a deployment |
| Long canonical model as the boundary | metrics reading Excel directly | swapping the source (an API) touches only the loader |
| Comments in YAML per period | text inside the `.docx` | idempotent regeneration and reuse between monthly and semester |
| Clean rate as a lower bound over the total | restricted single-visit base | the base must exist in the client's files |
| Cover outside the PDF numbering | post-processing the footer | natural with two passes |
| Closed condition evaluator for charts | `eval` | the catalogue is editable YAML; `None` is false, never zero |
| Chart with an empty series is "not applicable" | drawing it empty | a surveys-only group satisfies `periods >= 2` but has no rate |

The full log of decisions taken beyond the specification is in [`docs/DECISIONES.md`](https://github.com/arielgiamportone/periodic-report-kit/blob/main/docs/DECISIONES.md).

## What was measured and how to reproduce it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 72 tests, about 40 s
ruff check . && ruff format --check .
```

```bash
reportkit demo --out out/demo --months 6
```

The demo writes six months of synthetic raw files (with the quirks every rule exists for:
drafts, lock files, wrong month labels, blank results, mixed files, duplicated controls, a sheet
that lies about its size, a UTC export) and generates a monthly and a semester report, tagged
"DATOS SINTÉTICOS" in the file name and on the cover.

| Measure | Result |
|---|---|
| Monthly report (5 groups, 50 controls, 1 500 items) | 15 pages, docx + pdf |
| Semester report (6 months) | 22 pages, 17 charts, 22 tables |
| Demo end to end (data + both reports with PDF) | about 16 s |
| Contrast of the generated monthly against its own model | 0 discrepancies, exit code 0 |
| Leak guard | tree and `git log -p` clean |

Other commands:

```bash
reportkit generate --type monthly --from 2026-03 --to 2026-03 --data out/demo/data --out out --pdf
```

```bash
reportkit comments --period 2026-03 --data out/demo/data --out out/comments
```

```bash
reportkit validate --period 2026-03 --delivered out/.../Informe_monthly_2026-03_2026-03.docx --data out/demo/data
```

```bash
reportkit md examples/demo_deck.md --docx --pptx --out out/md
```

Python API (names match the public exports of `reportkit`):

```python
from reportkit import load_range, summarize, build_report, contrast, md_to_pptx
```

## Known limits

- The cover background of the demo brand is drawn from the declared geometry; the path that
  rasterises a real letterhead (`scripts/build_brand_kit.py --from-template`) needs LibreOffice.
- Fonts are not embedded in the `.docx`; the resolved family name is written into the styles.
- Only `.xlsx`, `.xlsm` and `.csv` inputs.
- Palettes are taken from `brand.yaml` as they are; the kit does not validate contrast or
  colour-vision separation, so charts always add direct labels and a legend.
- Cover geometry was verified by rendering with LibreOffice on Linux.

## How it was built

Three-phase clean room: a specification was written from the original work without code; this
repository was implemented in a separate session with no access to that code, from the
specification and the public documentation of OOXML, python-docx, python-pptx, matplotlib,
xhtml2pdf and pypdf; a third phase reviews the result against the source before publication. A
leak-guard test with an obfuscated blocklist runs in CI over the tree and the git history.

## Attribution

Patterns developed during my work at Intervalor Data and published with permission. Independent clean-room implementation with synthetic data; it contains no code or data from the company or its clients.

License: MIT.
