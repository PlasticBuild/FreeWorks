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


RED = "color: #c00000;"
PROMPTS = ("please select", "please pick", "please specify", "select ", "pick ", "click ", "choose ", "specify ")
# a prompt that names a mistake is an error after all
NOT_PROMPT = ("not ", "n't", "cannot", "can't", "failed", "invalid", "error", "too ", "must ", "only ")


def is_prompt(text):
    low = (text or "").strip().lower()
    if not low.startswith(PROMPTS):
        return False
    return not any(word in low for word in NOT_PROMPT)


def _restyle(label, prompt):
    try:
        if prompt:
            if label.property("swMessage") != "info" or label.styleSheet():
                label.setStyleSheet("")
                label.setProperty("swMessage", "info")
                label.setProperty("swstyle_warning", False)
                from PySide import QtCore
                label.setAttribute(QtCore.Qt.WA_StyledBackground, True)
                label.style().unpolish(label)
                label.style().polish(label)
        else:
            if label.property("swMessage") is not None or label.styleSheet() != RED:
                label.setProperty("swMessage", None)
                label.setStyleSheet(RED)
                label.style().unpolish(label)
                label.style().polish(label)
    except RuntimeError:
        return
    except Exception as _fw_err:
        _fw_log("pickprompt.py:restyle", _fw_err)


def style(label):
    """The label picks yellow message box or red error line by its text, on every setText."""
    if label is None or getattr(label, "_fw_prompt", False):
        return label
    try:
        own = label.setText

        def set_text(text, _own=own, _label=label):
            _restyle(_label, is_prompt(text))
            _own(text)
        label.setText = set_text
        label._fw_prompt = True
        from PySide import QtWidgets
        # the box as tall as its text (Rip's page gave the spare height to the line: a tall yellow box)
        label.setSizePolicy(label.sizePolicy().horizontalPolicy(), QtWidgets.QSizePolicy.Maximum)
        _restyle(label, is_prompt(label.text()))
    except Exception as _fw_err:
        _fw_log("pickprompt.py:style", _fw_err)
    return label
