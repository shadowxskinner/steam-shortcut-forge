"""Configuring emulators.

Every other provider discovers what it manages. An emulator has to be
described, so this is the one place in Kairo where the user tells it something
rather than the other way round.

The shape follows Dolphin: an emulator owns several ROM folders, and each
folder carries its own extensions and its own system name. Cemu and PCSX2 use
one folder and leave the system blank; nothing about the editor changes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from kairo import emulators as emu
from kairo import systems
from kairo.qt import work
from kairo.qt import theme as Q
from kairo.ui import theme as T


def _field(placeholder: str, value: str = "") -> QLineEdit:
    box = QLineEdit(value)
    box.setPlaceholderText(placeholder)
    return box


class FolderRow(QFrame):
    """One ROM folder: where it is, what counts, and what to call it.

    Two lines rather than one. A path is far longer than anything beside it,
    and competing for width in a single row left it showing its own tail —
    which is how you end up unsure whether the right folder is even in there.
    """

    def __init__(self, folder: emu.RomFolder | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("well")
        folder = folder or emu.RomFolder("")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.S3, T.S3, T.S3, T.S3)
        outer.setSpacing(T.S2)

        self.path = _field("Folder your games are in", folder.path)
        browse = QPushButton("Choose…")
        browse.setObjectName("secondary")
        browse.setFixedHeight(Q.H_BUTTON)
        browse.clicked.connect(lambda _c: self._browse())
        self.remove = QPushButton("Remove")
        self.remove.setObjectName("danger")
        self.remove.setFixedHeight(Q.H_BUTTON)

        top = QHBoxLayout()
        top.setSpacing(T.S2)
        top.addWidget(self.path, 1)
        top.addWidget(browse)
        top.addWidget(self.remove)
        outer.addLayout(top)

        self.extensions = _field(".iso .rvz", " ".join(folder.extensions))
        self.system = _field("System, optional", folder.system)
        # How many files this row actually matches, updated as you type. A
        # folder in the wrong box or an extension typed .rvs instead of .rvz
        # both look fine until something says "no files".
        self.matched = QLabel("")
        self.matched.setObjectName("meta")
        self._recount_serial = 0
        self._recount_timer = QTimer(self)
        self._recount_timer.setSingleShot(True)
        self._recount_timer.setInterval(200)
        self._recount_timer.timeout.connect(self.recount)

        bottom = QHBoxLayout()
        bottom.setSpacing(T.S2)
        for caption, widget, stretch in (("File types", self.extensions, 2),
                                         ("System", self.system, 1)):
            label = QLabel(caption)
            label.setObjectName("micro")
            bottom.addWidget(label)
            bottom.addWidget(widget, stretch)
        bottom.addWidget(self.matched)
        outer.addLayout(bottom)

        self.path.textChanged.connect(lambda text: self._path_changed(text))
        self.extensions.textChanged.connect(lambda _t: self._schedule_recount())
        self._path_changed(folder.path)

    def _path_changed(self, text: str) -> None:
        self.path.setToolTip(text)
        self._schedule_recount()

    def _schedule_recount(self) -> None:
        # Invalidate an in-flight count immediately, but wait until the user
        # pauses before walking a potentially huge disk tree again.
        self._recount_serial += 1
        self._recount_timer.start()

    def _browse(self) -> None:
        start = self.path.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "ROM folder", start)
        if chosen:
            self.path.setText(chosen)

    def recount(self) -> None:
        self._recount_timer.stop()
        self._recount_serial += 1
        serial = self._recount_serial
        folder = self.value()
        if not folder.path:
            self.matched.setText("")
            return
        root = Path(folder.path).expanduser()
        if not root.is_dir():
            self.matched.setText("no folder")
            return
        if not folder.extensions:
            self.matched.setText("no types")
            return
        self.matched.setText("Counting…")

        def count_files():
            try:
                count = sum(1 for p in root.rglob("*")
                            if folder.matches(p.name) and p.is_file())
            except OSError:
                count = None
            return serial, count

        work.submit(count_files, on_done=self._recounted)

    def _recounted(self, result) -> None:
        serial, count = result
        if serial != self._recount_serial:
            return
        if count is None:
            self.matched.setText("unreadable")
            return
        self.matched.setText(f"{count} file{'' if count == 1 else 's'}")

    def value(self) -> emu.RomFolder:
        # Extensions are typed however people type them - ".iso, rvz" is as
        # valid as ".iso .rvz". Splitting on both keeps the field forgiving.
        raw = self.extensions.text().replace(",", " ").split()
        return emu.RomFolder(self.path.text(), tuple(raw),
                             self.system.text()).normalised()


class SystemPicker(QDialog):
    """Pick a system rather than describe one.

    Every comparable tool ships a catalogue - ES-DE's es_systems.xml, Steam
    ROM Manager's community presets - because the alternative is asking a
    person to know that GameCube means .rvz. Systems whose emulator is
    already installed are listed first; the rest stay reachable, and so does
    describing something by hand.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add emulator")
        self.setMinimumWidth(560)
        self.setObjectName("dialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.chosen: systems.Detection | None = None
        self.manual = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD)
        layout.setSpacing(Q.GAP)

        note = QLabel("Kairo knows the file types and the usual emulator for "
                      "each system. It also checks the emulator's own game "
                      "list and common ROM folders, so installed setups often "
                      "arrive ready to add.")
        note.setObjectName("meta")
        note.setWordWrap(True)
        layout.addWidget(note)

        holder = QWidget()
        listing = QVBoxLayout(holder)
        listing.setContentsMargins(0, 0, 0, 0)
        listing.setSpacing(T.S1)
        for found in systems.detect():
            listing.addWidget(self._row(found))
        listing.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        other = QPushButton("Something else — describe it myself")
        other.setObjectName("secondary")
        other.setFixedHeight(Q.H_BUTTON)
        other.clicked.connect(self._describe)
        layout.addWidget(other, 0, Qt.AlignLeft)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _row(self, found: "systems.Detection") -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(T.S2)

        name = QLabel(found.system.display())
        name.setObjectName("rowNameOn" if found.installed else "rowName")
        detail = QLabel(" ".join(found.system.extensions[:4]))
        detail.setObjectName("meta")

        state = QLabel("installed" if found.installed else "not found")
        state.setObjectName("meta")
        state.setFixedWidth(Q.W_LABEL)

        add = QPushButton("Add")
        add.setObjectName("primary" if found.installed else "secondary")
        add.setFixedHeight(Q.H_BUTTON)
        add.clicked.connect(lambda _c, f=found: self._take(f))

        line.addWidget(name)
        line.addWidget(detail, 1)
        line.addWidget(state)
        line.addWidget(add)
        return row

    def _take(self, found: "systems.Detection") -> None:
        self.chosen = found
        self.accept()

    def _describe(self) -> None:
        self.manual = True
        self.accept()

    def emulator(self) -> emu.Emulator:
        """The catalogue entry as a configured emulator, ready to edit."""
        if self.chosen is None:
            return emu.Emulator()
        system = self.chosen.system
        return emu.Emulator(
            name=system.emulator or system.name,
            executable=self.chosen.executable,
            icon=self.chosen.icon,
            arguments=(*self.chosen.arguments, emu.ROM_PLACEHOLDER),
            folders=(emu.RomFolder(self.chosen.roms, system.extensions,
                                   system.name),)).normalised()


class EmulatorDialog(QDialog):
    """Add or edit one emulator."""

    def __init__(self, emulator: emu.Emulator | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Emulator")
        self.setMinimumWidth(900)
        # Without this the dialog takes the system palette, so it is dark on
        # a dark desktop theme and light on a light one while the window
        # behind it stays Kairo's own colour either way.
        self.setObjectName("dialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._original = emulator
        emulator = emulator or emu.Emulator()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD)
        layout.setSpacing(Q.GAP)

        self.name = _field("Dolphin", emulator.name)
        self.executable = _field("/usr/bin/dolphin-emu", emulator.executable)
        self.arguments = _field(emu.ROM_PLACEHOLDER,
                                " ".join(emulator.arguments))

        find = QPushButton("Choose…")
        find.setObjectName("secondary")
        find.setFixedHeight(Q.H_BUTTON)
        find.clicked.connect(lambda _c: self._find_executable())

        for label, widget, extra in (("Name", self.name, None),
                                     ("Executable", self.executable, find)):
            line = QHBoxLayout()
            line.setSpacing(T.S2)
            caption = QLabel(label)
            caption.setObjectName("meta")
            caption.setFixedWidth(Q.W_LABEL)
            line.addWidget(caption)
            line.addWidget(widget, 1)
            if extra is not None:
                line.addWidget(extra)
            layout.addLayout(line)

        heading = QLabel("ROM FOLDERS")
        heading.setObjectName("micro")
        layout.addWidget(heading)

        columns = QLabel("One row per system. Dolphin wants one for GameCube "
                         "and another for Wii; most emulators want one row.")
        columns.setObjectName("meta")
        columns.setWordWrap(True)
        layout.addWidget(columns)


        holder = QWidget()
        self.folders = QVBoxLayout(holder)
        self.folders.setContentsMargins(0, 0, 0, 0)
        self.folders.setSpacing(T.S2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        add = QPushButton("Add folder")
        add.setObjectName("secondary")
        add.setFixedHeight(Q.H_BUTTON)
        add.clicked.connect(lambda _c: self._add_folder())
        layout.addWidget(add, 0, Qt.AlignLeft)

        # Arguments last, and described as optional. Sitting above the folder
        # list it read as the next thing to fill in, and a ROM folder got
        # typed into it.
        advanced = QHBoxLayout()
        advanced.setSpacing(T.S2)
        caption = QLabel("Arguments")
        caption.setObjectName("meta")
        caption.setFixedWidth(Q.W_LABEL)
        advanced.addWidget(caption)
        advanced.addWidget(self.arguments, 1)
        layout.addLayout(advanced)
        hint = QLabel(f"Optional. {emu.ROM_PLACEHOLDER} is replaced with the "
                      "game's file, and is added for you if you leave it out. "
                      "This is not where the ROM folder goes.")
        hint.setObjectName("meta")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.rows: list[FolderRow] = []
        for folder in emulator.folders or (emu.RomFolder(""),):
            self._add_folder(folder)

        buttons = QDialogButtonBox(QDialogButtonBox.Save |
                                   QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _find_executable(self) -> None:
        start = self.executable.text().strip() or "/usr/bin"
        chosen, _f = QFileDialog.getOpenFileName(self, "Emulator", start)
        if chosen:
            self.executable.setText(chosen)

    def _add_folder(self, folder: emu.RomFolder | None = None) -> None:
        row = FolderRow(folder, self)
        row.remove.clicked.connect(lambda _c, r=row: self._drop_folder(r))
        self.rows.append(row)
        self.folders.addWidget(row)

    def _drop_folder(self, row: FolderRow) -> None:
        if row not in self.rows:
            return
        self.rows.remove(row)
        self.folders.removeWidget(row)
        row.setParent(None)
        row.deleteLater()

    def value(self) -> emu.Emulator:
        folders = tuple(row.value() for row in self.rows if row.value().path)
        keep_id = self._original.id if self._original else ""
        return emu.Emulator(id=keep_id, name=self.name.text(),
                            executable=self.executable.text(),
                            arguments=tuple(self.arguments.text().split()),
                            folders=folders).normalised()

    def _accept(self) -> None:
        """Refuse to save something that cannot work, and say why.

        Storing a broken emulator would show an empty section with no
        explanation, which is a worse outcome than a dialog that will not
        close yet.
        """
        problems = self.value().problems()
        if problems:
            QMessageBox.warning(self, "Not ready yet", "\n".join(problems))
            return
        self.accept()


class EmulatorsCard(QFrame):
    """The Settings section listing configured emulators."""

    def __init__(self, context, on_change=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.ctx = context
        self._on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD)
        layout.setSpacing(T.S3)

        heading = QLabel("Emulators")
        heading.setObjectName("pane")
        note = QLabel("Point Kairo at an emulator and its ROM folders, and "
                      "each game becomes a launcher shortcut you can give "
                      "artwork to. One emulator can cover several systems.")
        note.setObjectName("meta")
        note.setWordWrap(True)
        note.setMaximumWidth(Q.W_MEASURE)
        layout.addWidget(heading)
        layout.addWidget(note)

        self.list = QVBoxLayout()
        self.list.setSpacing(T.S2)
        layout.addLayout(self.list)

        add = QPushButton("Add emulator…")
        add.setObjectName("secondary")
        add.setFixedHeight(Q.H_BUTTON)
        add.clicked.connect(lambda _c: self._add())
        layout.addWidget(add, 0, Qt.AlignLeft)

        self._rebuild()

    # -- state -------------------------------------------------------------

    def _configured(self) -> list[emu.Emulator]:
        return emu.load(self.ctx.config)

    def _write(self, emulators: list[emu.Emulator]) -> None:
        from kairo import config as config_store

        self.ctx.config[emu.CONFIG_KEY] = emu.store(emulators)
        config_store.save(self.ctx.config)
        self._rebuild()
        if self._on_change is not None:
            self._on_change()

    # -- rows --------------------------------------------------------------

    def _rebuild(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        configured = self._configured()
        if not configured:
            empty = QLabel("No emulators yet.")
            empty.setObjectName("meta")
            self.list.addWidget(empty)
            return

        for index, emulator in enumerate(configured):
            self.list.addWidget(self._row(index, emulator))

    def _row(self, index: int, emulator: emu.Emulator) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(T.S2)

        name = QLabel(emulator.name)
        name.setObjectName("rowNameOn")
        systems = ", ".join(f.system or Path(f.path).name
                            for f in emulator.folders) or "no folders"
        detail = QLabel(systems)
        detail.setObjectName("meta")

        edit = QPushButton("Edit")
        edit.setObjectName("secondary")
        edit.setFixedHeight(Q.H_BUTTON)
        edit.clicked.connect(lambda _c, i=index: self._edit(i))

        remove = QPushButton("Remove")
        remove.setObjectName("danger")
        remove.setFixedHeight(Q.H_BUTTON)
        remove.clicked.connect(lambda _c, i=index: self._remove(i))

        problems = emulator.problems()
        if problems:
            detail.setText(problems[0])
            detail.setToolTip("\n".join(problems))

        line.addWidget(name)
        line.addWidget(detail, 1)
        line.addWidget(edit)
        line.addWidget(remove)
        return row

    # -- actions -----------------------------------------------------------

    def _add(self) -> None:
        """Catalogue first, hand-written second."""
        picker = SystemPicker(self)
        if picker.exec() != QDialog.Accepted:
            return
        prefilled = None if picker.manual else picker.emulator()
        dialog = EmulatorDialog(prefilled, self)
        if dialog.exec() == QDialog.Accepted:
            self._write([*self._configured(), dialog.value()])

    def _edit(self, index: int) -> None:
        configured = self._configured()
        if not (0 <= index < len(configured)):
            return
        dialog = EmulatorDialog(configured[index], self)
        if dialog.exec() == QDialog.Accepted:
            configured[index] = dialog.value()
            self._write(configured)

    def _remove(self, index: int) -> None:
        """Removing an emulator forgets the configuration, not the shortcuts.

        Any shortcuts already created stay where they are and stay listed
        under Changes, so this can never silently delete something the user
        put on their desktop.
        """
        configured = self._configured()
        if not (0 <= index < len(configured)):
            return
        emulator = configured[index]
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle("Remove emulator")
        confirm.setText(f"Remove {emulator.name} from Kairo?")
        confirm.setInformativeText(
            "Shortcuts you already created stay where they are, and are still "
            "listed under Changes. Only this configuration is forgotten.")
        confirm.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Yes:
            return
        del configured[index]
        self._write(configured)
