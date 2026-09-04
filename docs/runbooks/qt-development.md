# Qt development

Kairo's default `kairo` command launches the CustomTkinter frontend. The Qt
frontend drives the same backend and is available as `kairo-qt` or
`python -m kairo.qt`.

## Set up

From the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[qt,test]"
```

## Run and verify

```bash
.venv/bin/python -B -m kairo.qt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest
```

Run `.venv/bin/python -B -m kairo.qt --help` for the supported appearance and
blur diagnostic flags. The optional native KWin blur bridge can be built with
`./kairo/qt/native/build.sh`; it is not required for the Qt frontend or tests.

The archived milestone notes in `docs/archive/qt-shell-milestone.md` preserve
the original design and debugging history, but are not current instructions.
