# Kairo Agent Guide

## Evidence and scope

- The human request and acceptance criteria define what **SHOULD** happen; executed behavior and source evidence define what **DOES** happen.
- Distinguish verified facts, inference, and user reports. A test, config, or file is not proof that current behavior works unless the relevant behavior is executed.
- Attribute another agent's evidence; never present another agent's run as your own.
- Inspect affected code and authoritative documentation before editing. Keep changes scoped and avoid unrelated refactors.
- If a material requirement remains ambiguous, ask the human instead of inventing behavior.
- Report exact verification performed, what was not verified, and every changed file.

## Project map

- `README.md` — product overview, supported install paths, architecture summary, and current development commands.
- `README-QT.md` — Qt frontend runbook (shipping UI, launch flags, verification).
- `kairo/qt/__main__.py` and `kairo/qt/` — Qt entry point and frontend.
- `kairo/__main__.py` and `kairo/ui/` — legacy CustomTkinter entry point and frontend; Qt does not import it.
- `kairo/providers/` and `kairo/artwork/` — application discovery and artwork sources.
- `kairo/actions.py`, `adoption.py`, `ledger.py`, `migration.py`, `matching.py`, and `paths.py` — launcher-changing core and migration boundaries.
- `tests/` — pytest suite; use isolated HOME/XDG fixtures where applicable and account for documented environment-sensitive detection tests.
- `pyproject.toml` — Python packaging and dependencies. `PKGBUILD` and `.SRCINFO` — Arch packaging.
- `release.sh` — release/publish automation, not a routine verification command.
- `.ai/context.md` — concise durable safety and compatibility constraints; read it before project claims or changes.
- `docs/system-icons-spec.md` — detailed system-application design.

## Durable safety constraints

- Launcher changes stay user-level; never edit system or vendor desktop files.
- Authority to overwrite, restore, or delete comes from ownership markers in the live launcher, not filenames or history alone.
- Preserve legacy ownership compatibility and downgrade paths; ambiguous, foreign, malformed, or unreadable entries remain untouched.
- Resetting artwork and deleting a generated launcher are separate operations.
- Tests should use isolated HOME/XDG state where applicable. Some system-detection tests remain environment-sensitive because they can observe real installed desktop applications.
- Tests must never write to the developer's real config, icons, or application entries.

## Workflow and verification

- Use a task branch for meaningful changes. Do not force-push or rewrite shared history; stage intended paths deliberately, and leave merging to the human.
- Run relevant focused tests, then the documented full suite when a change can affect shared behavior.
- Never invoke `release.sh` without explicit release authorization: it commits, pushes, tags, updates checksums, and publishes repository state.
- A contradiction between implementation and `.ai/context.md` is BLOCKING and must be resolved in the same change.

## Review and secrets

- Reviewers start read-only and do not silently repair findings. Report evidence-based issues and suppress style-only noise unless requested.
- A BLOCKING finding is a concrete correctness defect, security issue, data-loss risk, requirement violation, or meaningful regression. State its location, trigger, expected behavior, actual behavior, and evidence.
- A NON-BLOCKING finding is a concrete maintainability or testability issue.
- Never commit or report API keys, tokens, credentials, private keys, or secret environment contents.
