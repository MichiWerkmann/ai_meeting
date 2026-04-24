# Repository Guidelines

## Project Structure & Module Organization
Create three top-level folders before committing new work: `src/` for agent logic, `tests/` for automated checks, and `assets/` for meeting transcripts or prompt templates. Within `src/`, group related modules under feature folders (for example, `src/summary/processor.py`), keep shared utilities in `src/common/`, and expose runnable entry points via `src/__main__.py` so `python -m src` works. Place experimental notebooks in `docs/notebooks/` and keep generated artifacts out of version control.

## Build, Test, and Development Commands
Set up the environment once with `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`. Run `python -m src` for local smoke tests of the latest meeting workflow. Execute `pytest -q` for the fast unit suite and `pytest -m integration` when touching data adapters or API clients. Use `ruff check src tests` before pushing to catch lint violations, and run `black src tests` if the formatter reports changes.

## Coding Style & Naming Conventions
Target Python 3.11, 4-space indentation, and explicit typing for any public function. Modules and variables follow `snake_case`, classes use `PascalCase`, and CLI entry points live in files named `cli.py`. Prefer dataclasses for immutable payloads and wrap side-effect-heavy helpers behind small interfaces in `src/common/interfaces.py`. Keep public functions under 30 lines and guard script execution with `if __name__ == "__main__":`.

## Testing Guidelines
Pytest is the single source of truth. Add a matching test file under `tests/` for every new module and name test functions `test_<behavior>`. Use fixtures for transcripts or mock API keys instead of hard-coding sensitive data. Keep coverage at or above 85% (run `pytest --cov=src` to verify) and include regression tests whenever fixing production defects.

## Commit & Pull Request Guidelines
Use Conventional Commits (`feat: add diarization agent`, `fix(meeting_parser): guard empty agenda`). Keep commits small and focused, referencing Azure Board or GitHub issue IDs where applicable. Every pull request needs a short problem statement, validation notes (commands run), and screenshots or log snippets when UI or API responses change. Request review from another agent before merging and ensure CI is green.
