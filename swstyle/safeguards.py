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

import sys

import FreeCAD as App
from PySide import QtCore

try:
    import shiboken6 as _shiboken
except ImportError:                                 # pragma: no cover (PySide2 builds)
    try:
        import shiboken2 as _shiboken
    except ImportError:
        _shiboken = None

PACKAGES = ("swstyle", "smcore")
WRAPPED = "_fw_guarded"


def valid(obj):
    if obj is None:
        return False
    if _shiboken is None:
        return True
    try:
        return _shiboken.isValid(obj)
    except Exception:
        return True                                 # not a Qt wrapper: nothing to check


def _chain_valid(obj):
    """obj and every parent widget up to its window are still there."""
    if _shiboken is None:
        return True
    is_valid = _shiboken.isValid
    try:
        w = obj.parent()
        for _i in range(64):
            if w is None:
                return True
            if not is_valid(w):
                return False
            w = w.parent()
    except (RuntimeError, AttributeError, TypeError):
        return False
    return True


# Events a window gets by the thousand while it is being built (a 300-part drawing opening sends ~76k):
# only the filter and the watched object are checked for these, not the whole window chain. The chain
# walk stays for everything else (paint, hover, timers, focus, hide, close), where the crashes came from.
_LIGHT = set()
for _n in ("ChildAdded", "ChildPolished", "LayoutRequest", "Move", "Resize", "MetaCall",
           "DynamicPropertyChange", "Show", "ShowToParent", "ZOrderChange", "WindowTitleChange", "FontChange",
           "StyleChange", "Polish", "PolishRequest", "ModifiedChange", "LocaleChange", "ToolTipChange",
           "StatusTip", "WhatsThisClicked", "EnabledChange", "ActionAdded", "ActionChanged", "ActionRemoved"):
    try:
        _LIGHT.add(getattr(QtCore.QEvent.Type, _n))
    except AttributeError as _fw_err:
        _fw_log("safeguards.py:87", _fw_err)
_LIGHT = frozenset(_LIGHT)


_TYPES_ON = [None]


def _interest(fn, cls):
    """The event types fn acts on (evtypes reads its source), or None: call it for every type."""
    live = getattr(cls, "FW_EVENT_TYPES", None)
    if live is not None:
        return live         # extapps/63: a dispatcher that keeps its own up-to-date set of the types it handles
    if _TYPES_ON[0] is None:
        try:
            _TYPES_ON[0] = not App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("EventTypesOff", False)
        except Exception:
            _TYPES_ON[0] = True
    if not _TYPES_ON[0]:
        return None
    try:
        from . import evtypes
        return evtypes.interest(fn, cls)
    except Exception:
        return None


def _guard(cls):
    fn = cls.__dict__.get("eventFilter")
    if fn is None or getattr(fn, WRAPPED, False):
        return False

    _is_valid = _shiboken.isValid if _shiboken is not None else None
    _types = {}                 # class of the filter object -> the event types its code acts on, or None for all

    def eventFilter(self, obj, event, _fn=fn, _is_valid=_is_valid, _types=_types):
        if self is None or obj is None:
            return False
        if not isinstance(event, QtCore.QEvent):
            return False        # PySide 6 can hand a filter a layout item instead of the event (Table-Pattern edit)
        try:
            kind = event.type()
        except RuntimeError:
            return False
        try:
            wanted = _types[self.__class__]
        except KeyError:
            wanted = _types[self.__class__] = _interest(_fn, self.__class__)
        if wanted is not None and kind not in wanted:
            return False        # extapps/57: this filter's code does nothing for this type of event
        if _is_valid is not None:
            try:
                if not _is_valid(self) or not _is_valid(obj):
                    return False
            except Exception:
                pass                    # not a Qt wrapper: nothing to check (as valid() did)
        light = kind in _LIGHT
        if not light and _is_valid is not None:
            try:
                w = obj.parent()
                for _i in range(64):
                    if w is None:
                        break
                    if not _is_valid(w):
                        return False
                    w = w.parent()
            except (RuntimeError, AttributeError, TypeError):
                return False
        try:
            return _fn(self, obj, event)
        except RuntimeError:
            return False

    setattr(eventFilter, WRAPPED, True)
    eventFilter.__wrapped__ = fn
    eventFilter.__doc__ = fn.__doc__
    try:
        setattr(cls, "eventFilter", eventFilter)
    except (TypeError, AttributeError):
        return False
    return True


def _ours(cls):
    mod = getattr(cls, "__module__", "") or ""
    return mod.split(".")[0] in PACKAGES


def guard_loaded():
    ""
    n = 0
    for name, mod in list(sys.modules.items()):
        if mod is None or name.split(".")[0] not in PACKAGES:
            continue
        for value in list(vars(mod).values()):
            try:
                if isinstance(value, type) and issubclass(value, QtCore.QObject) and _ours(value):
                    for klass in value.__mro__:
                        if isinstance(klass, type) and _ours(klass) and _guard(klass):
                            n += 1
            except Exception:
                continue
    return n


_orig_install = None
_orig_single = None


def _single_shot(*args, **kwargs):
    ""


    try:
        if len(args) == 2 and not kwargs and isinstance(args[0], int):
            fn = args[1]
            owner = getattr(fn, "__self__", None)
            if isinstance(owner, QtCore.QObject) and callable(fn) and \
                    (sys._getframe(1).f_globals.get("__name__", "") or "").split(".")[0] in PACKAGES:
                if not valid(owner):
                    return None
                return _orig_single(args[0], owner, fn)
    except Exception as _fw_err:
        _fw_log("safeguards.py:162", _fw_err)
    return _orig_single(*args, **kwargs)


def _install_event_filter(self, filter_obj, *args):
    try:
        cls = type(filter_obj)
        if _ours(cls):
            for klass in cls.__mro__:
                if _ours(klass):
                    _guard(klass)
    except Exception as _fw_err:
        _fw_log("safeguards.py:174", _fw_err)
    try:
        if HOLD is not None and not args and _ours(type(filter_obj)) and \
                isinstance(self, QtCore.QCoreApplication) and self is QtCore.QCoreApplication.instance():
            HOLD[:] = [f for f in HOLD if f is not filter_obj]       # installed again: moves to the end, as in Qt
            HOLD.append(filter_obj)
            return None
    except Exception as _fw_err:
        _fw_log("safeguards.py:hold", _fw_err)
    return _orig_install(self, filter_obj, *args)


# extapps/64: the add-on's application-wide filters asked for during start-up, installed by release() once the main
# window is up (Qt would call each of them for every start-up event: about 125,000)
HOLD = None
_orig_remove = None


def _remove_event_filter(self, filter_obj, *args):
    try:
        if HOLD is not None and any(f is filter_obj for f in HOLD):
            HOLD[:] = [f for f in HOLD if f is not filter_obj]
            return None
    except Exception as _fw_err:
        _fw_log("safeguards.py:hold-remove", _fw_err)
    return _orig_remove(self, filter_obj, *args)


def release():
    """Installs the held application filters, in the order they were asked for (idempotent)."""
    global HOLD
    held, HOLD = HOLD, None
    if not held:
        return 0
    app = QtCore.QCoreApplication.instance()
    n = 0
    for f in held:
        try:
            if _shiboken is None or _shiboken.isValid(f):
                _orig_install(app, f)
                n += 1
        except Exception as _fw_err:
            _fw_log("safeguards.py:release", _fw_err)
    App.Console.PrintLog("FreeWorks: %d application event filters installed after start-up\n" % n)
    return n


def install():
    ""

    global _orig_install, _orig_single, _orig_remove, HOLD
    # a switch to start without the guard (PC check 11-14: a crash at 125 % while Dark was applied from
    # the Python console showed the guard's frame; this tells whether the guard is part of it)
    if App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("SafeguardsOff", False):
        App.Console.PrintLog("FreeCAD: event filter guard off (SafeguardsOff)\n")
        return 0
    if _orig_install is None:
        try:
            _orig_install = QtCore.QObject.installEventFilter
            QtCore.QObject.installEventFilter = _install_event_filter
            if _orig_remove is None and not App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool(
                    "HoldAppFiltersOff", False):
                _orig_remove = QtCore.QObject.removeEventFilter
                QtCore.QObject.removeEventFilter = _remove_event_filter
                HOLD = []           # extapps/64: until startup calls release()
        except (TypeError, AttributeError) as error:
            _orig_install = None
            App.Console.PrintLog("FreeCAD: event filter guard (install hook): %s\n" % error)
    if _orig_single is None:
        try:
            _orig_single = QtCore.QTimer.singleShot
            QtCore.QTimer.singleShot = staticmethod(_single_shot)
        except (TypeError, AttributeError) as error:
            _orig_single = None
            App.Console.PrintLog("FreeCAD: timer guard: %s\n" % error)
    n = guard_loaded()
    App.Console.PrintLog("FreeCAD: event filters guarded: %d\n" % n)
    return n
