"""The Changes destination, read-only for this milestone.

Everything Kairo owns is listed, including entries adopted from a Steam
Shortcut Forge migration, exactly as the Tk shell shows them. Restore and
Remove are present so the layout can be judged and are disabled, because
destructive behaviour is not wired until the shell has been validated.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger, deletes_launcher
from kairo.qt.widgets import IconWell
from kairo.qt import theme as Q
from kairo.ui import theme as T

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
    def __init__(self, record: ChangeRecord, parent=None):
        super().__init__(parent)
        self.record = None
        self._signature = None
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
        self.undo.setEnabled(False)
        self.undo.setToolTip("Not wired yet — this milestone is read-only")
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
        detail = (f"{source}  ·  {T.format_date(record.applied_at)}"
                  if allowed else reason)
        self.meta.setText(T.ellipsize(detail, 62))
        created = deletes_launcher(record.action)
        self.undo.setText("Reset" if created else "Restore")
        self.remove.setVisible(created)


class ChangesPane(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.ctx = context
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
        for label, name in (("Clean up unused artwork", "secondary"),
                            ("Restore all", "secondary")):
            button = QPushButton(label)
            button.setObjectName(name)
            button.setEnabled(False)
            button.setToolTip("Not wired yet — this milestone is read-only")
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

    def refresh(self) -> None:
        records = self.ctx.ledger.records()
        signature = tuple(record_signature(record) for record in records)
        if signature == self._signature:
            return
        self._signature = signature
        self._records = records
        self.count.setText(f"{len(records)} application(s) customised by Kairo")

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

    def _bind_records(self, records) -> None:
        for row in self._row_widgets.values():
            row.setVisible(False)
        for index, record in enumerate(records):
            row = self._row_widgets.get(record.key)
            if row is None:
                row = ChangeRow(record, self.holder)
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
