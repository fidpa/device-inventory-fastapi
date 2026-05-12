# Contributing to device-inventory-fastapi

Thanks for taking the time to contribute! This document explains how to report issues, propose changes, and submit pull requests.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

## Reporting Bugs

Before opening a bug report, please:

1. **Search existing issues** to make sure the problem hasn't already been reported.
2. **Check the latest release** — your bug may already be fixed.
3. **Reproduce on a clean install** if possible.

When opening a bug report, include:

- A clear, descriptive title.
- Steps to reproduce (smallest example that triggers the bug).
- Expected behaviour vs. actual behaviour.
- Python version, OS, and FastAPI / SQLite versions.
- Relevant log output (with secrets and personal data redacted).

## Suggesting Features

Feature suggestions are welcome via GitHub Issues. Please describe:

- The use case (what problem does this solve?).
- Why the existing functionality is insufficient.
- A rough sketch of the proposed UX or API.

Keep in mind the project's design constraints (see "Design Goals" below) — proposals that conflict with them are unlikely to be accepted, but may inspire alternative solutions.

## Security Vulnerabilities

**DO NOT open a public GitHub issue for security vulnerabilities.** Follow the responsible disclosure process described in [`SECURITY.md`](SECURITY.md).

## Development Setup

```bash
# Clone and install
git clone https://github.com/fidpa/device-inventory-fastapi
cd device-inventory-fastapi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov httpx ruff

# Run the app locally
cp .env.example .env
# Fill in AUTH_SECRET, AUTH_PASSWORD_HASH, NEXTCLOUD_*
python3 -m uvicorn src.app:app --reload --port 8004
```

## Style Guidelines

### Python

- **Linter**: [Ruff](https://docs.astral.sh/ruff/) (config in `.ruff.toml`).
  ```bash
  ruff check src/ scripts/ tests/
  ruff format --check src/ scripts/ tests/
  ```
- **Type hints**: required on new public functions. Modern syntax (`str | None`, `list[int]`) — Python 3.10+.
- **Docstrings**: short, English, action-oriented. One-liner for trivial helpers, full docstring for endpoints / business logic.
- **Imports**: stdlib → third-party → local, separated by blank lines (Ruff handles this with `I` rules).

### HTML / CSS / JavaScript

- HTML: 4-space indent, semantic markup, `aria-*` attributes on interactive elements.
- CSS: BEM-ish class naming (`.progress-fill`, `.toner-fill`); CSS variables for theming.
- JS: vanilla ES2020+, no frameworks. Avoid jQuery.

### SQL

- All queries **parameterized** (no string concatenation with user input).
- DDL changes update `ensure_db()` in `src/app.py` and add a note to `CHANGELOG.md`.

## Commit Messages

Conventional Commits format:

```
feat: add CSV export for printer scans
fix: handle empty serial_number in CIM output
docs: clarify NEXTCLOUD_PATH format
test: cover rate-limit edge case
refactor: extract bcrypt verification into helper
```

Keep messages in English, imperative mood, ≤ 72 characters in the subject line.

## Pull Request Process

1. Fork the repository and create a feature branch (`feat/your-feature`).
2. Make your changes with tests where appropriate.
3. Run `ruff check`, `ruff format --check`, and `pytest` locally — all must pass.
4. Update `CHANGELOG.md` under `[Unreleased]` if user-visible behaviour changes.
5. Open a PR with a clear description of:
   - What changes
   - Why it's needed
   - How to test it
6. CI must pass before review.

## Design Goals (please respect when proposing changes)

- **Single-file architecture**: `src/app.py` stays a single file. Routes can be extracted into modules only if `app.py` exceeds ~3,000 LOC.
- **No frontend build step**: Jinja2 + vanilla JS only. No npm, no webpack, no React.
- **SQLite, single-server**: no Redis, no message queue, no migrations framework. Schema changes go into `ensure_db()`.
- **Standalone systemd deployment**: no Docker, no Kubernetes. The whole stack must run from `setup/setup.sh` on a fresh Ubuntu / Debian server.
- **English-only**: documentation, code, comments, and UI text are all in English.
- **Privacy first**: never log PII or secrets. Redact before logging.

## Releasing

(Maintainer reference — contributors don't need to do this.)

1. Update `CHANGELOG.md`: move `[Unreleased]` items to a new versioned section with today's date.
2. Tag the release: `git tag -a v1.X.0 -m "Release 1.X.0"`.
3. Push the tag: `git push origin v1.X.0`.
4. Create a GitHub Release referencing the changelog entry.
