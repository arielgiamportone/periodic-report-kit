# Contributing

Thanks for your interest in `reportkit`.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Ground rules

- **Synthetic data only.** Fixtures and examples must come from `reportkit.synthetic` or a
  generator script in `scripts/`. Never commit a real spreadsheet, document or export, not even
  an "anonymised" one.
- **No secrets, no local paths.** CI runs `gitleaks`; the leak-guard test (`tests/test_no_leaks.py`)
  scans the tree and the git history.
- **Rules live in YAML.** A business criterion that may change belongs in `config/*.yaml`, with a
  test, not in an `if` inside the code.
- **Public interfaces are typed** and documented. Code and identifiers are in English; user-facing
  report text defaults to Spanish and is configurable.
- Keep `CHANGELOG.md` updated under *Unreleased*.

## Pull requests

1. Branch from `main`.
2. Add or update tests for every rule you touch.
3. Make sure `pytest`, `ruff check .` and the leak guard pass locally.
4. Describe the decision and the alternatives you discarded; `docs/DECISIONES.md` keeps the log.
