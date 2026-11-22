# SPDX-License-Identifier: LGPL-2.1-or-later
""



_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks"
QUESTION = "Would you like to rebuild the document before saving?"
REBUILD = "Rebuild and save the document (recommended)"
NO_REBUILD = "Save the document without rebuilding"
NO_REBUILD_SUB = "The document will not be up to date until the next time it is rebuilt."
FOOTER = ("When features are edited or externally-referenced documents change, those changes are not "
          "reflected in the model until it is rebuilt.")


def needs_rebuild(doc):
    for o in doc.Objects:
        try:
            if "Touched" in o.State or "Invalid" in o.State or o.mustExecute():
                return True
        except Exception as _fw_err:
            _fw_log("rebuildsave.py:36", _fw_err)
    return False


ERRORS_PAGE, ERRORS_TEXT = "Messages/Errors/Warnings", "Warn me when saving documents with rebuild errors"
ERRORS_HOOK = []        # checks: callables(doc, bad) -> True (save) / False (cancel) / None (show the box)


def failed(doc):
    """The features whose last rebuild failed."""
    return [o for o in doc.Objects if "Invalid" in (o.State or []) or "Error" in (o.State or [])]


def ask_errors(doc):
    """Warn before saving a document with rebuild errors (Options > Messages/Errors/Warnings >
    Warn me when saving documents with rebuild errors). True to save, False to cancel. msgbox-1119"""
    try:
        from . import optionspages
        on = optionspages.stored(ERRORS_PAGE, ERRORS_TEXT, True)
    except Exception:
        optionspages, on = None, True
    bad = failed(doc)
    if not on or not bad:
        return True
    for hook in ERRORS_HOOK:
        answer = hook(doc, bad)
        if answer is not None:
            return bool(answer)
    box = QtWidgets.QDialog(Gui.getMainWindow())
    box.setWindowTitle("FreeCAD")
    box.setObjectName("FW_RebuildErrorsSave")
    lay = QtWidgets.QVBoxLayout(box)
    top = QtWidgets.QHBoxLayout()
    icon = QtWidgets.QLabel()
    from . import msgicons
    icon.setPixmap(msgicons.pixmap("warning", 32))
    icon.setAlignment(QtCore.Qt.AlignTop)
    top.addWidget(icon)
    names = ", ".join(o.Label for o in bad[:6]) + (" and %d more" % (len(bad) - 6) if len(bad) > 6 else "")
    text = QtWidgets.QLabel("<b>This document has rebuild errors.</b><br>Not rebuilt: %s.<br><br>"
                            "Save it with the errors?" % names)
    text.setObjectName("FW_RebuildErrorsText")
    text.setWordWrap(True)
    top.addWidget(text, 1)
    lay.addLayout(top)
    row = QtWidgets.QHBoxLayout()
    again = QtWidgets.QCheckBox("Don't show again")
    again.setObjectName("FW_RebuildErrorsDontShow")
    row.addWidget(again)
    row.addStretch(1)
    what = QtWidgets.QPushButton("What's Wrong")
    what.setObjectName("FW_RebuildErrorsWhatsWrong")
    save = QtWidgets.QPushButton("Save")
    save.setObjectName("FW_RebuildErrorsSaveButton")
    save.setDefault(True)
    cancel = QtWidgets.QPushButton("Cancel")
    cancel.setObjectName("FW_RebuildErrorsCancel")
    save.clicked.connect(box.accept)
    cancel.clicked.connect(box.reject)

    def whats_wrong():
        box.reject()
        try:
            from . import whatswrong
            whatswrong.show(doc)
        except Exception as _fw_err:
            _fw_log("rebuildsave.py:whatswrong", _fw_err)
    what.clicked.connect(whats_wrong)
    for b in (what, save, cancel):
        row.addWidget(b)
    lay.addLayout(row)
    box.setMinimumWidth(420)
    ASKED[:] = [box]
    ok = box.exec() == QtWidgets.QDialog.Accepted
    if ok and again.isChecked() and optionspages is not None:
        try:
            optionspages.set_stored(ERRORS_PAGE, ERRORS_TEXT, False)
        except Exception as _fw_err:
            _fw_log("rebuildsave.py:again", _fw_err)
    return ok


ASKED = []


def ask(doc):
    """True to go on with the save (rebuilt or not), False to cancel."""
    if not needs_rebuild(doc):
        return True
    p = App.ParamGet(PARAM)
    kept = p.GetInt("RebuildOnSave", 0)
    if kept in (1, 2):
        if kept == 1:
            doc.recompute()
        return True
    box = QtWidgets.QDialog(Gui.getMainWindow())
    box.setWindowTitle("FreeCAD")
    box.setObjectName("FW_RebuildSave")
    lay = QtWidgets.QVBoxLayout(box)
    top = QtWidgets.QHBoxLayout()
    icon = QtWidgets.QLabel()
    from . import msgicons
    icon.setPixmap(msgicons.pixmap("warning", 32))
    icon.setAlignment(QtCore.Qt.AlignTop)
    top.addWidget(icon)
    question = QtWidgets.QLabel(QUESTION)
    question.setStyleSheet("font-size: 11pt; color: #1f4e9c;")
    question.setWordWrap(True)
    top.addWidget(question, 1)
    lay.addLayout(top)
    choice = {"v": 0}

    def link(text, sub, v):
        b = QtWidgets.QCommandLinkButton(text, sub) if sub else QtWidgets.QCommandLinkButton(text)
        b.clicked.connect(lambda: (choice.__setitem__("v", v), box.accept()))
        lay.addWidget(b)
        return b

    link(REBUILD, "", 1).setDefault(True)
    link(NO_REBUILD, NO_REBUILD_SUB, 2)
    row = QtWidgets.QHBoxLayout()
    again = QtWidgets.QCheckBox("Don't show again")
    row.addWidget(again)
    row.addStretch(1)
    cancel = QtWidgets.QPushButton("Cancel")
    cancel.clicked.connect(box.reject)
    row.addWidget(cancel)
    lay.addLayout(row)
    foot = QtWidgets.QLabel(FOOTER)
    foot.setWordWrap(True)
    foot.setStyleSheet("color: #555; border-top: 1px solid #ccc; padding-top: 6px;")
    lay.addWidget(foot)
    box.setMinimumWidth(460)
    box.exec()
    v = choice["v"]
    if v == 0:
        return False
    if again.isChecked():
        p.SetInt("RebuildOnSave", v)
    if v == 1:
        doc.recompute()
    return True
