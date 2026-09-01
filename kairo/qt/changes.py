"""The Changes destination: everything Kairo owns, and how to undo it.

Entries adopted from a Steam Shortcut Forge migration are included, exactly
as the Tk shell shows them.

Restore is wired through ``kairo.actions`` and the provider's own writer, so
the marker inside the launcher file remains the only thing that authorises a
destructive change. This pane decides *when* to ask; it never decides whether
Kairo is allowed to, and it never touches a launcher file itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from kairo import actions
from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger, deletes_launcher
from kairo.qt import work
from kairo.qt.widgets import IconWell
from kairo.qt import theme as Q
from kairo.tasks import Skip
from kairo.ui import theme as T

#: One activity, so starting a restore cancels whatever was outstanding and a
#: result that arrives from the superseded one is dropped rather than painted.
ACTIVITY_RESTORE = "changes:restore"

# A change row carries two image wells and up to two buttons, so it is notably
# heavier than a library row. Forty is still several viewports at 900px while
# keeping the first visit comfortably inside one frame-sized interaction.
CHANGES_PAGE = 40


def previous_icon(record: ChangeRecord):
    """The original icon, resolved - often a bare theme name, not a path."""
    return resolve_icon(record.original_icon) if record.original_icon else None


def _file_version(value: str):
    if not value:
        return None
    try:
        stat = Path(value).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def record_signature(record: ChangeRecord):
    """Everything that can change how a history row is painted.

    File versions are included because a launcher can be restored or replaced
    outside Kairo while its ledger record stays unchanged.
    """
    return (record.key, record.name, record.action, record.original_icon,
            record.applied_icon, record.source_id, record.source_label,
            record.applied_at, record.adopted, _file_version(record.target),
            _file_version(record.applied_icon))


class ChangeRow(QFrame):
    #: The row never restores anything itself. It reports which record was
    #: asked about and lets the pane, which owns the context, do the work.
    restore_requested = Signal(object)

    def __init__(self, record: ChangeRecord, parent=None):
        super().__init__(parent)
        self.record = None
        self._signature = None
        self._restorable = False
        self.setObjectName("row")
        self.setFixedHeight(Q.H_ROW)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.S3, T.S2, T.S4, T.S2)
        layout.setSpacing(T.S3)

        self.before = IconWell(Q.WELL_ROW, self)
        arrow = QLabel("→")
        arrow.setObjectName("meta")
        self.after = IconWell(Q.WELL_ROW, self)
        layout.addWidget(self.before)
        layout.addWidget(arrow)
        layout.addWidget(self.after)

        text = QVBoxLayout()
        text.setSpacing(3)
        self.name = QLabel("")
        self.name.setObjectName("rowName")
        self.meta = QLabel("")
        self.meta.setObjectName("rowMeta")
        text.addWidget(self.name)
        text.addWidget(self.meta)
        layout.addLayout(text, 1)

        self.undo = QPushButton("")
        self.undo.setObjectName("secondary")
        # clicked carries a checked flag a one-argument Signal cannot take.
        self.undo.clicked.connect(
            lambda _checked: self.restore_requested.emit(self.record))
        layout.addWidget(self.undo)
        self.remove = QPushButton("Remove")
        self.remove.setObjectName("danger")
        self.remove.setEnabled(False)
        self.remove.setToolTip("Not wired yet — this milestone is read-only")
        layout.addWidget(self.remove)
        self.bind(record)

    def bind(self, record: ChangeRecord) -> None:
        signature = record_signature(record)
        if signature == self._signature:
            return
        self._signature = signature
        self.record = record
        self.before.show_path(previous_icon(record), "—")
        self.after.show_path(record.applied_icon_path, "—")
        self.name.setText(T.ellipsize(record.name, 34))
        source = ("Existing customization" if record.adopted
                  else record.source_label or record.source_id or "a local file")
        allowed, reason = Ledger.restorable(record)
        self._restorable = allowed
        detail = (f"{source}  ·  {T.format_date(record.applied_at)}"
                  if allowed else reason)
        self.meta.setText(T.ellipsize(detail, 62))
        created = deletes_launcher(record.action)
        self.undo.setText("Reset" if created else "Restore")
        # The marker check that authorises the change also decides whether the
        # button can be pressed, so a row whose launcher was hand-edited says
        # why instead of failing once clicked.
        self.undo.setEnabled(allowed)
        self.undo.setToolTip("" if allowed else reason)
        self.remove.setVisible(created)

    def set_busy(self, busy: bool) -> None:
        """Disable while any restore is running, so clicks cannot stack up."""
        self.undo.setEnabled(False if busy else bool(self.record is not None
                                                     and self._restorable))
        self.remove.setEnabled(False)


class ChangesPane(QWidget):
    #: A restore changes what every library pane and the sidebar should show.
    changed = Signal()

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.ctx = context
        self._busy_now = False
        self._note = ""
        self.setObjectName("workspace")
        # A QWidget *subclass* does not paint a stylesheet background unless
        # it is told to; plain QWidget instances do. Both panes name
        # themselves #workspace, so without this they showed the default
        # palette instead of Kairo's backdrop — the reason Settings and
        # Changes read lighter than the library.
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_PANE, 0, Q.PAD_PANE, Q.PAD_PANE)
        layout.setSpacing(Q.GAP_WIDE)

        header = QWidget()
        header.setFixedHeight(Q.H_HEADER)
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T.S2)
        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        title = QLabel("Changes")
        title.setObjectName("title")
        self.count = QLabel("")
        self.count.setObjectName("subtitle")
        titles.addStretch(1)
        titles.addWidget(title)
        titles.addWidget(self.count)
        titles.addStretch(1)
        head.addLayout(titles)
        head.addStretch(1)
        self.cleanup_btn = QPushButton("Clean up unused artwork")
        self.cleanup_btn.setObjectName("secondary")
        self.cleanup_btn.setEnabled(False)
        self.cleanup_btn.setToolTip("Not wired yet")
        self.restore_all_btn = QPushButton("Restore all")
        self.restore_all_btn.setObjectName("secondary")
        self.restore_all_btn.clicked.connect(
            lambda _checked: self._restore_all())
        for button in (self.cleanup_btn, self.restore_all_btn):
            button.setFixedHeight(Q.H_BUTTON)
            head.addWidget(button, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(T.S2, T.S3, T.S2, T.S3)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.verticalScrollBar().valueChanged.connect(
            self._grow_if_near_bottom)
        self.holder = QWidget()
        self.rows = QVBoxLayout(self.holder)
        self.rows.setContentsMargins(0, 0, T.S2, 0)
        self.rows.setSpacing(Q.GAP_ROW)
        self.rows.addStretch(1)
        self._row_widgets: dict[str, ChangeRow] = {}
        self._empty = None
        self._signature = None
        self._records = []
        self._shown = 0
        self.scroll.setWidget(self.holder)
        card_layout.addWidget(self.scroll)
        layout.addWidget(card, 1)

        self.refresh()

    def refresh(self, force: bool = False) -> None:
        records = self.ctx.ledger.records()
        signature = tuple(record_signature(record) for record in records)
        if signature == self._signature and not force:
            return
        self._signature = signature
        self._records = records
        summary = f"{len(records)} application(s) customised by Kairo"
        self.count.setText(f"{summary}  ·  {self._note}" if self._note
                           else summary)

        wanted = {record.key for record in records}
        for key in list(self._row_widgets):
            if key in wanted:
                continue
            widget = self._row_widgets.pop(key)
            self.rows.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()

        if not records:
            self._shown = 0
            if self._empty is None:
                self._empty = QLabel("Kairo has not changed anything yet.\n\n"
                                     "Artwork you apply appears here, and you "
                                     "can put any of it back.")
                self._empty.setObjectName("empty")
                self._empty.setAlignment(Qt.AlignCenter)
                self.rows.insertWidget(0, self._empty, 1, Qt.AlignCenter)
            # An empty state pinned to the top-left of a large surface reads
            # as a failure to load. Centred, it reads as a state.
            return

        if self._empty is not None:
            self.rows.removeWidget(self._empty)
            self._empty.setParent(None)
            self._empty.deleteLater()
            self._empty = None
        self._shown = min(len(records), max(CHANGES_PAGE, self._shown))
        self._bind_records(records[:self._shown])

    # -- restoring ---------------------------------------------------------
    #
    # Everything below decides *when* to ask and what to say. None of it
    # writes: kairo.actions owns the writer, the writer consults the marker
    # inside the launcher file, and the ledger is updated by the same call.
    # A refusal comes back as Skip and is reported, not worked around.

    def _say(self, note: str) -> None:
        self._note = note
        self.refresh(force=True)

    def _busy(self, busy: bool, verb: str = "") -> None:
        """Disable every control while one restore is in flight.

        Repeated clicks are the reason: two restores of the same record race
        each other to delete the same file, and the second one fails on work
        the first already did.
        """
        self._busy_now = busy
        self.restore_all_btn.setEnabled(not busy)
        for row in self._row_widgets.values():
            row.set_busy(busy)
        if busy and verb:
            self._say(f"{verb}…")

    def _provider_for(self, record):
        return self.ctx.providers.get(record.provider_id)

    def _restore_one(self, record) -> None:
        if record is None or self._busy_now:
            return
        provider = self._provider_for(record)
        if provider is None:
            # A record written by a build that had a provider this one does
            # not. Nothing to restore through; say so rather than guess.
            self._say(f"{record.name}: no “{record.provider_id}” provider "
                      "in this build.")
            return

        # Asked here purely to word the question and to avoid prompting for
        # something that cannot happen. actions.restore_record checks it
        # again against the file, which is the check that authorises anything.
        allowed, reason = Ledger.restorable(record)
        if not allowed:
            self._say(f"{record.name}: {reason}")
            return

        entry = actions.entry_from_record(record)
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle(self.sender().text()
                               if isinstance(self.sender(), QPushButton)
                               else "Restore")
        # The writer knows what restoring means for its own kind of entry —
        # dropping artwork from a shortcut Kairo made is not the same act as
        # deleting an override, and they must not share a sentence.
        confirm.setText(provider.writer().restore_prompt(entry))
        confirm.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Yes:
            return

        token = self.ctx.tokens.start(ACTIVITY_RESTORE)
        self._busy(True, "Restoring")
        name = record.name

        def run():
            try:
                actions.restore_record(record, self.ctx.providers,
                                       ledger=self.ctx.ledger)
            except Skip as skip:
                # Refused for a reason the user should read, not an error.
                return ("skipped", str(skip))
            return ("restored", "")

        def done(outcome) -> None:
            if token.cancelled:
                return                      # a newer restore superseded this
            state, detail = outcome
            self._busy(False)
            self._say(f"Restored {name}." if state == "restored"
                      else f"{name}: {detail}")
            self.changed.emit()

        def failed(message: str) -> None:
            if token.cancelled:
                return
            self._busy(False)
            self._say(f"{name}: {message}")
            # Emitted even on failure: an attempt can leave the entry in a
            # different state than the panes currently believe.
            self.changed.emit()

        work.submit(run, on_done=done, on_failed=failed)

    def _restore_all(self) -> None:
        if self._busy_now:
            return
        records = self.ctx.ledger.records()
        if not records:
            self._say("Nothing to restore.")
            return

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle("Restore all")
        confirm.setText(f"Undo all {len(records)} change(s) Kairo has made?")
        confirm.setInformativeText(
            "Each launcher entry is checked for Kairo's own marker first. "
            "Anything edited outside Kairo is left alone and reported.")
        confirm.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Yes:
            return

        token = self.ctx.tokens.start(ACTIVITY_RESTORE)
        self._busy(True, "Restoring all")

        def run():
            # Ownership is revalidated per record inside restore_all, and it
            # saves the ledger whatever happens, so a failure partway through
            # cannot lose the ones already undone.
            return actions.restore_all(self.ctx.ledger, self.ctx.providers,
                                       token=token)

        def done(summary) -> None:
            if token.cancelled:
                # Closing cancels the token, and the pane may be going away.
                return
            self._busy(False)
            self._say(self._describe(summary))
            self.changed.emit()
            details = [*summary.failures, *summary.skips]
            if details:
                report = QMessageBox(self)
                report.setIcon(QMessageBox.Warning if summary.failed
                               else QMessageBox.Information)
                report.setWindowTitle("Restore all")
                report.setText(self._describe(summary))
                report.setDetailedText("\n".join(details))
                report.exec()

        def failed(message: str) -> None:
            if token.cancelled:
                return
            self._busy(False)
            self._say(f"Restore all stopped: {message}")
            self.changed.emit()

        work.submit(run, on_done=done, on_failed=failed)

    @staticmethod
    def _describe(summary) -> str:
        """Counts as they actually are, including the ones that did nothing."""
        head = (f"Cancelled after {summary.processed} of {summary.total}"
                if summary.cancelled
                else f"Restored {summary.succeeded} of {summary.total}")
        parts = []
        if summary.skipped:
            parts.append(f"{summary.skipped} skipped")
        if summary.failed:
            parts.append(f"{summary.failed} failed")
        return f"{head} — {', '.join(parts)}." if parts else f"{head}."

    def _bind_records(self, records) -> None:
        for row in self._row_widgets.values():
            row.setVisible(False)
        for index, record in enumerate(records):
            row = self._row_widgets.get(record.key)
            if row is None:
                row = ChangeRow(record, self.holder)
                row.restore_requested.connect(self._restore_one)
                self._row_widgets[record.key] = row
            else:
                row.bind(record)
            self.rows.insertWidget(index, row)
            row.setVisible(True)

    def _grow_if_near_bottom(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - value > Q.H_ROW * 3:
            return
        if self._shown >= len(self._records):
            return
        self._shown = min(len(self._records), self._shown + CHANGES_PAGE)
        self._bind_records(self._records[:self._shown])
