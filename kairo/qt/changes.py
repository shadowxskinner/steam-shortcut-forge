"""The Changes destination, read-only for this milestone.

Everything Kairo owns is listed, including entries adopted from a Steam
Shortcut Forge migration, exactly as the Tk shell shows them. Restore and
Remove are present so the layout can be judged and are disabled, because
destructive behaviour is not wired until the shell has been validated.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger, deletes_launcher
from kairo.qt.widgets import IconWell
from kairo.qt import theme as Q
from kairo.ui import theme as T


def previous_icon(record: ChangeRecord):
    """The original icon, resolved - often a bare theme name, not a path."""
    return resolve_icon(record.original_icon) if record.original_icon else None


class ChangeRow(QFrame):
    def __init__(self, record: ChangeRecord, parent=None):
        super().__init__(parent)
        self.record = record
        self.setObjectName("row")
        self.setFixedHeight(Q.H_ROW)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.S3, T.S2, T.S4, T.S2)
        layout.setSpacing(T.S3)

        before = IconWell(Q.WELL_ROW, self)
        before.show_path(previous_icon(record), "—")
        arrow = QLabel("→")
        arrow.setObjectName("meta")
        after = IconWell(Q.WELL_ROW, self)
        after.show_path(record.applied_icon_path, "—")
        layout.addWidget(before)
        layout.addWidget(arrow)
        layout.addWidget(after)

        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(T.ellipsize(record.name, 34))
        name.setObjectName("rowName")
        source = ("Existing customization" if record.adopted
                  else record.source_label or record.source_id or "a local file")
        allowed, reason = Ledger.restorable(record)
        detail = (f"{source}  ·  {T.format_date(record.applied_at)}"
                  if allowed else reason)
        meta = QLabel(T.ellipsize(detail, 62))
        meta.setObjectName("rowMeta")
        text.addWidget(name)
        text.addWidget(meta)
        layout.addLayout(text, 1)

        undo = QPushButton("Reset" if deletes_launcher(record.action) else "Restore")
        undo.setObjectName("secondary")
        undo.setEnabled(False)
        undo.setToolTip("Not wired yet — this milestone is read-only")
        layout.addWidget(undo)
        if deletes_launcher(record.action):
            remove = QPushButton("Remove")
            remove.setObjectName("danger")
            remove.setEnabled(False)
            remove.setToolTip("Not wired yet — this milestone is read-only")
            layout.addWidget(remove)


class ChangesPane(QWidget):
    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.ctx = context
        self.setObjectName("workspace")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_PANE, Q.PAD_PANE, Q.PAD_PANE, Q.PAD_PANE)
        layout.setSpacing(Q.GAP_WIDE)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = QLabel("Changes")
        title.setObjectName("title")
        self.count = QLabel("")
        self.count.setObjectName("meta")
        titles.addWidget(title)
        titles.addWidget(self.count)
        head.addLayout(titles)
        head.addStretch(1)
        for label, name in (("Clean up unused artwork", "secondary"),
                            ("Restore all", "secondary")):
            button = QPushButton(label)
            button.setObjectName(name)
            button.setEnabled(False)
            button.setToolTip("Not wired yet — this milestone is read-only")
            head.addWidget(button)
        layout.addLayout(head)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(T.S3, T.S3, T.S3, T.S3)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.rows = QVBoxLayout(self.holder)
        self.rows.setContentsMargins(0, 0, T.S2, 0)
        self.rows.setSpacing(Q.GAP_ROW)
        self.rows.addStretch(1)
        self.scroll.setWidget(self.holder)
        card_layout.addWidget(self.scroll)
        layout.addWidget(card, 1)

        self.refresh()

    def refresh(self) -> None:
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        records = self.ctx.ledger.records()
        self.count.setText(f"{len(records)} application(s) customised by Kairo")
        if not records:
            empty = QLabel("Kairo has not changed anything yet.\n\n"
                           "Artwork you apply appears here, and you can put "
                           "any of it back.")
            empty.setObjectName("empty")
            self.rows.insertWidget(0, empty)
            return
        for index, record in enumerate(records):
            self.rows.insertWidget(index, ChangeRow(record, self.holder))
