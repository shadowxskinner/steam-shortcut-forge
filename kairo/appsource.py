"""Where an installed application came from.

Under Applications, "everything with a .desktop file" is one list of several
hundred entries whose only ordering is alphabetical. The useful question a
person asks of it is which of these the package manager put here, which came
from the AUR or a manual build, and which are Flatpaks - that is what decides
whether an icon change survives an update.

This is read-only metadata. It does not change an application's key, the
filename a shortcut is written to, its ledger identity, or which writer
handles it. It only decides which bucket a row is shown in.

Three rules govern it:

* **Evidence, not naming.** A path under an exports directory, an `X-Flatpak`
  key, a package that actually owns the file. Never a guess from the name.
* **Every entry lands somewhere.** Anything that cannot be established
  degrades to Local / Other. Nothing is dropped for being unclassifiable; a
  list that silently loses rows is worse than one with a vague bucket.
* **Batched, never per row.** One `pacman -Qo` for the whole scan. The
  per-row version is a subprocess per visible line, which on a 2,000 entry
  list is a fork bomb in slow motion.

`pacman -Qm` reports packages foreign to the configured repositories. That
usually means the AUR, but it equally covers a package built and installed by
hand, so the bucket is "Foreign / AUR" rather than "AUR". Calling it AUR would
assert something the package database does not say.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from kairo import paths

#: Bucket ids. ``ALL`` is not a classification - it is the whole list.
ALL = "all"
ARCH = "arch"
FOREIGN = "foreign"
FLATPAK = "flatpak"
LOCAL = "local"

LABELS = (
    (ALL, "All"),
    (ARCH, "Arch packages"),
    (FOREIGN, "Foreign / AUR"),
    (FLATPAK, "Flatpak"),
    (LOCAL, "Local / Other"),
)

BUCKETS = tuple(bucket for bucket, _label in LABELS if bucket != ALL)

#: Batched so one scan is a handful of calls, and small enough that the
#: argument list cannot overflow.
CHUNK = 200

#: Long enough for a cold package database on a slow disk, short enough that a
#: wedged package manager cannot hold the scan open.
TIMEOUT = 20


def _run(argv):
    """Run a command and return stdout, or None if it could not run at all.

    ``shell=False`` always: these arguments are paths chosen by whatever
    installed an application, and ``Photo Editor (2024); rm -rf ~.desktop`` is
    a legal filename.

    ``LC_ALL=C`` because the output is parsed. Pacman localises "is owned by",
    and a German or Japanese desktop would otherwise classify everything as
    Local.
    """
    env = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   timeout=TIMEOUT, env=env, shell=False)
    except (OSError, subprocess.SubprocessError):
        # Not installed, not executable, killed, timed out. All the same
        # answer: this machine cannot tell us, so nothing is claimed.
        return None
    if completed.returncode != 0 and not completed.stdout:
        return None
    return completed.stdout


def _flatpak_roots():
    """Directories a Flatpak export actually lands in."""
    roots = [Path("/var/lib/flatpak/exports/share/applications")]
    data_home = os.environ.get("XDG_DATA_HOME")
    home = Path(data_home) if data_home else Path.home() / ".local" / "share"
    roots.append(Path(home) / "flatpak" / "exports" / "share" / "applications")
    return roots


def _exec_is_flatpak(exec_line: str) -> bool:
    """Whether a parsed Exec actually launches through flatpak.

    Parsed, not searched: an application whose name or comment mentions
    flatpak is not a Flatpak. An unmatched quote is a malformed entry, which
    is a reason to say nothing rather than to raise into the middle of a scan.
    """
    try:
        argv = shlex.split(exec_line, posix=True)
    except ValueError:
        return False
    for token in argv:
        name = Path(token).name
        if name == "flatpak":
            return "run" in argv
        if name in ("env", "sh", "bash") or token.startswith("-"):
            continue
        if "=" in token and not token.startswith("/"):
            continue                    # VAR=value prefixes on an env line
        return False
    return False


def _reads_as_flatpak(path: Path, roots) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            pass
    if not paths.is_readable_file(path):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("X-Flatpak") and "=" in line:
            if line.split("=", 1)[1].strip():
                return True
        elif line.startswith("Exec=") and _exec_is_flatpak(line[5:]):
            return True
    return False


def _owners(files, run):
    """Map each path to the package owning it, for those that are owned.

    The output is ``<path> is owned by <package> <version>``, with the middle
    localised. Taking the first token as the path and the second-to-last as
    the package survives translation; unowned files go to stderr and simply do
    not appear.
    """
    owned = {}
    for start in range(0, len(files), CHUNK):
        chunk = [str(item) for item in files[start:start + CHUNK]]
        out = run(["pacman", "-Qo", "--"] + chunk)
        if not out:
            continue
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            owned[parts[0]] = parts[-2]
    return owned


def _foreign_packages(run):
    """Package names Pacman reports as foreign to the configured repos."""
    out = run(["pacman", "-Qm"])
    if not out:
        return set()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if parts:
            names.add(parts[0])
    return names


def classify(files, *, run=_run, roots=None):
    """Bucket each desktop-file path. Never raises, never drops a path.

    ``run`` and ``roots`` are injected so tests describe a machine rather than
    depend on the one they happen to run on.
    """
    roots = list(_flatpak_roots() if roots is None else roots)
    result = {}
    remaining = []
    for item in files:
        path = Path(item)
        try:
            if _reads_as_flatpak(path, roots):
                result[str(item)] = FLATPAK
                continue
        except Exception:
            # A file can vanish, or become unreadable, between the scan that
            # listed it and this. That is Local, not a crashed scan.
            result[str(item)] = LOCAL
            continue
        remaining.append(item)

    if remaining:
        owned = _owners(remaining, run)
        foreign = _foreign_packages(run) if owned else set()
        for item in remaining:
            package = owned.get(str(item))
            if package is None:
                # Deliberately left unset: unowned, unreadable, and anything
                # the package manager declined to answer for all converge on
                # the same fallback below, so there is one place that decides
                # what "we could not tell" means.
                continue
            result[str(item)] = FOREIGN if package in foreign else ARCH

    # The guarantee: every path leaves with a bucket. A list that silently
    # drops the rows it could not classify is worse than a vague label.
    for item in files:
        result.setdefault(str(item), LOCAL)
    return result


def counts(buckets):
    """How many entries sit in each bucket, including the ``all`` total."""
    tally = {bucket: 0 for bucket, _label in LABELS}
    for bucket in buckets:
        tally[ALL] += 1
        if bucket in tally and bucket != ALL:
            tally[bucket] += 1
        elif bucket != ALL:
            tally[LOCAL] += 1
    return tally


def label_for(bucket: str, tally=None) -> str:
    """The pill caption, with a count when one is known."""
    name = dict(LABELS).get(bucket, dict(LABELS)[LOCAL])
    if not tally:
        return name
    return f"{name}  {tally.get(bucket, 0)}"
