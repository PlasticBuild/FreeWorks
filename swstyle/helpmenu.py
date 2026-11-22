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

import os
import platform
import sys
import tempfile
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .widgets import alive

Qt = QtCore.Qt
WEB = "UseWebHelp"

INTRO = """<h2>Introducing the interface</h2>
<p>The interface makes FreeCAD look and work like a feature-based mechanical CAD program.
You can keep its standard workbenches; the interface changes the window around them.</p>
<ul>
<li><b>CommandManager</b>: the tabbed ribbon at the top (Features, Sketch, Evaluate and so on).</li>
<li><b>FeatureManager</b>: the tree on the left. It lists History, Sensors, Annotations, the bodies,
Material, the three planes and Origin, and then the features in the order they were made. Drag the blue
rollback bar to step back through the history.</li>
<li><b>PropertyManager</b>: the panel each feature opens, with OK and Cancel at the top.</li>
<li><b>Heads-up toolbar</b>: the view tools at the top of the graphics area.</li>
<li><b>Shortcut bar</b>: press S in the graphics area for the commands that fit what you are doing.</li>
</ul>
<p>Parts are FreeCAD PartDesign bodies, assemblies use FreeCAD's Assembly workbench and drawings use TechDraw,
so the files are ordinary .FCStd files that any FreeCAD opens.</p>"""

TWO_D = """<h2>Moving from 2D to 3D</h2>
<p>In 2D drafting you draw every view of a part yourself. In FreeCAD you build the part once in 3D,
and the drawing views are projected from it.</p>
<ol>
<li><b>Sketch the profile, not the view.</b> Pick a plane (Front, Top or Right), click Sketch, and draw one
outline. A sketch is turned into a solid, so it does not need hidden lines or centre marks.</li>
<li><b>Use relations and dimensions in place of construction lines.</b> Horizontal, Vertical, Coincident and
Equal keep the shape; Smart Dimension sets the sizes. A black sketch is fully defined.</li>
<li><b>Add material with features.</b> Extruded Boss/Base pulls the profile into a solid, Extruded Cut removes
material, and Fillet and Chamfer finish the edges. Each feature is a row in the FeatureManager that you can edit later.</li>
<li><b>Make the drawing last.</b> File &gt; Make Drawing from Part places standard views. Model Items brings in the
part's own dimensions, so the drawing changes when the part does.</li>
</ol>"""

TUTORIALS = (
    ("Lesson 1: A first part", [
        ("Start a part", "New", "File > New, then Part."),
        ("Sketch on the Top plane", "Sketch", "Pick Top Plane in the FeatureManager, then click Sketch."),
        ("Draw a rectangle", "CornerRectangle", "Drag out a rectangle from the origin."),
        ("Dimension it", "SmartDimension", "Click each edge and type its length; the sketch turns black."),
        ("Extrude it", "BossExtrude", "Extruded Boss/Base, type a depth, then click OK."),
        ("Round the edges", "Fillet", "Fillet, pick the top edges, set the radius, then click OK."),
    ]),
    ("Lesson 2: Changing a part", [
        ("Edit a feature", "EditFeature", "Pick a feature in the FeatureManager, then Edit Feature."),
        ("Roll back", None, "Drag the blue rollback bar above a feature; the features under it are greyed out."),
        ("Reorder", None, "Drag a feature to another place in the tree. A move that would break it is refused."),
        ("Equations", "Equations", "Tools > Equations: global variables drive the dimensions."),
    ]),
    ("Lesson 3: Assemblies and drawings", [
        ("Make an assembly", "MakeAssembly", "File > Make Assembly from Part."),
        ("Mate the parts", "cmd:SWStyle_Mate", "Mate, pick two faces, then choose Coincident or Concentric."),
        ("Make a drawing", "MakeDrawing", "File > Make Drawing from Part, then drag in the views."),
        ("Bring in dimensions", "DrawModelItems", "Annotation > Model Items puts the part's dimensions on the views."),
    ]),
)

WHATS_NEW = (
    ("ConfigurationManager", "Derived configurations, Rebuild/Save Mark and the Configuration Publisher.", None),
    ("Equations", "Global variables, equations and names such as D1@Sketch1.", "Equations"),
    ("File Properties", "Summary, Custom and Configuration Specific properties.", "FileProperties"),
    ("DimXpertManager", "The left pane's fourth tab lists the MBD annotations.", None),
    ("Feature dimensions", "Annotations folder > Show Feature Dimensions shows every feature's dimensions.", None),
    ("Sensors", "Add Sensor watches a mass property and warns when it goes out of its limits.", "Sensor"),
    ("Reorder by drag", "Drag features in the FeatureManager; a move that would break the part is refused.", None),
    ("View Decals", "The DisplayManager lists every decal, so you can edit, hide or remove it.", None),
)

RELEASE = """<h2>Release Notes</h2>
<p>Interface version {version} for FreeCAD {freecad}.</p>
<h3>In this release</h3>
<ul>{items}</ul>
<h3>Known limits</h3>
<ul>
<li>A FreeCAD file keeps only the active configuration's shape, so Rebuild/Save Mark rebuilds the marked
configurations and checks them when you save. It does not store their shapes.</li>
<li>Help, Tutorials and API Help open on this computer; Use Web Help switches Help to FreeCAD's online pages.</li>
</ul>"""


# --------------------------------------------------------------------------- facts
def version():
    try:
        import re
        text = (paths.ADDON_DIR / "package.xml").read_text(encoding="utf-8")
        m = re.search(r"<version>([^<]+)</version>", text)
        return m.group(1).strip() if m else "?"
    except Exception:
        return "?"


def freecad_version():
    v = App.Version()
    return ".".join(v[:3]) + ((" " + v[3]) if len(v) > 3 and v[3] else "")


def use_web():
    return paths.params().GetBool(WEB, False)


def set_use_web(on):
    paths.params().SetBool(WEB, bool(on))


# --------------------------------------------------------------------------- the pages
def _commands():
    """[(tab, [(key, label, tip, shortcut)])] from the CommandManager's own catalog."""
    from . import catalog
    out = []
    seen = set()

    def walk(spec, into):
        if isinstance(spec, str):
            if spec in catalog.BY_KEY and spec not in seen:
                seen.add(spec)
                into.append(spec)
        elif isinstance(spec, (tuple, list)):
            for s in spec:
                walk(s, into)
    for title, spec in catalog.TABS:
        keys = []
        walk(spec, keys)
        rows = []
        for k in keys:
            cmd = catalog.BY_KEY[k]
            rows.append((k, cmd.label, cmd.tip or "", _shortcut(cmd)))
        if rows:
            out.append((title, rows))
    return out


def _shortcut(cmd):
    try:
        for name in cmd.natives:
            a = Gui.Command.get(name)
            if a is not None:
                s = a.getShortcut()
                if s:
                    return s
    except Exception as _fw_err:
        _fw_log("helpmenu.py:190", _fw_err)
    return ""


def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def page(name):
    """The HTML of a help page by name."""
    if name == "intro":
        return INTRO
    if name == "2d3d":
        return TWO_D
    if name.startswith("cmd:"):
        from . import cmdhelp
        return cmdhelp.page(name[4:])
    if name == "commands":
        from . import catalog, cmdhelp
        parts = ["<h2>Commands</h2><p>Every command on the CommandManager tabs of parts, assemblies and drawings. "
                 "Click a name for its help page, or Run to start it.</p>"]
        heads = {"part": "Parts", "assembly": "Assemblies", "drawing": "Drawings"}
        mode_now = None
        for mode, title, keys in cmdhelp.tab_rows():
            if mode != mode_now:
                mode_now = mode
                parts.append("<h2>%s</h2>" % heads.get(mode, mode))
            parts.append("<h3>%s</h3><table cellspacing=4>" % _esc(title))
            for key in keys:
                cmd = catalog.BY_KEY[key]
                parts.append("<tr><td><a href='page:cmd:%s'>%s</a></td><td>%s</td><td><i>%s</i></td>"
                             "<td><a href='run:%s'>Run</a></td></tr>"
                             % (key, _esc(cmd.label), _esc(cmd.tip or ""), _esc(_shortcut(cmd)), key))
            parts.append("</table>")
        return "".join(parts)
    if name == "keys":
        from . import keys
        rows = "".join("<tr><td>%s</td><td>%s</td></tr>" % (_esc(_menu_text(c)), _esc(k)) for c, k in keys.KEYS if k)
        return "<h2>Keyboard shortcuts</h2><table cellspacing=4>%s</table>" % rows
    if name.startswith("lesson"):
        i = int(name[6:])
        title, steps = TUTORIALS[i]
        items = "".join("<li><b>%s</b>: %s%s</li>" % (_esc(s), _esc(t), (" <a href='run:%s'>Do it</a>" % k) if k else "")
                        for s, k, t in steps)
        nxt = ("<p><a href='page:lesson%d'>Next: %s</a></p>" % (i + 1, _esc(TUTORIALS[i + 1][0]))
               if i + 1 < len(TUTORIALS) else "<p><a href='page:tutorials'>All tutorials</a></p>")
        return "<p><a href='page:tutorials'>Tutorials</a> &gt; %s</p><h2>%s</h2><ol>%s</ol>%s" \
            % (_esc(title), _esc(title), items, nxt)
    if name == "tutorials":
        # one row per lesson: its name, how many steps, and what the steps cover
        rows = "".join(
            "<tr><td valign=top><a href='page:lesson%d'><b>%s</b></a><br><span style='color:#666'>%d steps: %s</span></td></tr>"
            % (i, _esc(t), len(steps), _esc(", ".join(s for s, _k, _t in steps)))
            for i, (t, steps) in enumerate(TUTORIALS))
        return "<h2>Tutorials</h2><p>Short lessons. Each step's link runs the command it names.</p>" \
            "<table cellspacing=8>%s</table>" % rows
    if name == "whatsnew":
        return "<h2>What's New in FreeCAD %s</h2><ul>%s</ul>" % (version(), "".join(
            "<li><b>%s</b>: %s%s</li>" % (_esc(t), _esc(d), (" <a href='run:%s'>Show me</a>" % k) if k else "")
            for t, d, k in WHATS_NEW))
    if name == "release":
        return RELEASE.format(version=version(), freecad=freecad_version(),
                              items="".join("<li>%s: %s</li>" % (_esc(t), _esc(d)) for t, d, _k in WHATS_NEW))
    if name == "api":
        return api_page()
    return "<h2>FreeCAD Help</h2>" + INTRO + "<p><a href='page:tutorials'>Tutorials</a> | " \
        "<a href='page:commands'>Commands</a> | <a href='page:keys'>Keyboard shortcuts</a> | " \
        "<a href='page:2d3d'>Moving from 2D to 3D</a></p>" + news_html()


NEWS_FEED = "https://blog.freecad.org/feed/"
_NEWS = {"items": None, "error": None}


def news_wanted():
    """Options > General > Show latest Technical Alerts and News in Welcome dialog."""
    try:
        from . import optionspages
        return bool(optionspages.stored("General", "Show latest Technical Alerts and News in Welcome dialog", True))
    except Exception:
        return True


def news_html():
    """The Technical Alerts and News section of the Welcome page (FreeCAD's news feed), or '' when off."""
    if not news_wanted():
        return ""
    items = _NEWS["items"]
    if items is None:
        body = "<p><i>%s</i></p>" % _esc(_NEWS["error"] or "Fetching the latest news...")
    elif not items:
        body = "<p><i>No news items.</i></p>"
    else:
        body = "<ul>%s</ul>" % "".join("<li><a href='%s'>%s</a></li>" % (_esc(u), _esc(t)) for t, u in items[:8])
    return "<h3>Technical Alerts and News</h3>" + body


def parse_feed(text):
    """(title, link) pairs from an RSS or Atom feed."""
    import re
    out = []
    for block in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", text, re.S):
        t = re.search(r"<title[^>]*>(.*?)</title>", block, re.S)
        u = re.search(r"<link[^>]*href=[\"']([^\"']+)", block) or re.search(r"<link[^>]*>(.*?)</link>", block, re.S)
        if t and u:
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", t.group(1), flags=re.S).strip()
            out.append((title, u.group(1).strip()))
    return out


def net_words(reply, what):
    """A failed request in plain words: a connection problem (offline, DNS, TLS, timeout) reads as no connection."""
    try:
        err = reply.error()
        code = int(getattr(err, "value", err))
    except Exception:
        code = 99
    if 1 <= code <= 9 or code in (99, 101, 102):
        return "No connection, so %s cannot be shown now." % what
    return "%s could not be fetched (%s)." % (what[0].upper() + what[1:], reply.errorString())


def fetch_news(done):
    """Fetches the feed once (QNetworkAccessManager) and calls done() when it has it."""
    if _NEWS["items"] is not None:
        return done()
    try:
        from PySide import QtNetwork
    except Exception as error:
        _NEWS["error"] = "No network module: %s" % error
        return done()
    mw = Gui.getMainWindow()
    nam = getattr(mw, "_fw_news_nam", None)
    if nam is None:
        nam = QtNetwork.QNetworkAccessManager(mw)
        mw._fw_news_nam = nam

    def finished(reply):
        try:
            if reply.error() == QtNetwork.QNetworkReply.NoError:
                _NEWS["items"] = parse_feed(bytes(reply.readAll()).decode("utf-8", "replace"))
            else:
                _NEWS["error"] = net_words(reply, "the news")
        except Exception as error:
            _NEWS["error"] = "The news could not be read: %s" % error
        reply.deleteLater()
        done()
    previous = _NEWS.get("slot")
    if previous is not None:
        try:
            nam.finished.disconnect(previous)
        except Exception as _fw_err:
            _fw_log("helpmenu.py:330", _fw_err)
    _NEWS["slot"] = finished
    nam.finished.connect(finished)
    nam.get(QtNetwork.QNetworkRequest(QtCore.QUrl(NEWS_FEED)))


def _menu_text(name):
    try:
        c = Gui.Command.get(name)
        if c is not None:
            return (c.getInfo() or {}).get("menuText", name).replace("&", "")
    except Exception as _fw_err:
        _fw_log("helpmenu.py:342", _fw_err)
    return name


API_MODULES = ("equations", "configmanager", "fileprops", "mbd", "reorder", "treefolders", "rollbackbar",
               "freezebar", "featuredims", "evaluate2", "customprops", "optionspages")


def api_page(module=None):
    import importlib
    import inspect
    if module is None:
        items = []
        for m in API_MODULES:
            try:
                mod = importlib.import_module("swstyle." + m) if "swstyle" in sys.modules else \
                    importlib.import_module(__package__ + "." + m)
                first = (inspect.getdoc(mod) or "").split("\n")[0]
            except Exception:
                first = ""
            items.append("<li><a href='api:%s'>%s</a>: %s</li>" % (m, m, _esc(first)))
        return "<h2>Interface API Help</h2><p>The Python modules of this interface, for macros. Use them as " \
               "<code>from %s import equations</code>.</p><ul>%s</ul>" % (__package__, "".join(items))
    mod = importlib.import_module(__package__ + "." + module)
    rows = []
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if name.startswith("_") or fn.__module__ != mod.__name__:
            continue
        try:
            sig = str(inspect.signature(fn))
        except Exception:
            sig = "(...)"
        rows.append("<dt><b>%s</b>%s</dt><dd>%s</dd>" % (name, _esc(sig), _esc(inspect.getdoc(fn) or "")))
    return "<h2>%s</h2><pre>%s</pre><dl>%s</dl><p><a href='page:api'>All modules</a></p>" % (
        module, _esc(inspect.getdoc(mod) or ""), "".join(rows))


# --------------------------------------------------------------------------- the help window
def alive_window(win):
    try:
        return win is not None and win.objectName() == "SWHelpWindow"
    except RuntimeError:
        return False


class HelpWindow(QtWidgets.QDialog):
    PAGES = (("Welcome", "home"), ("Tutorials", "tutorials"), ("Commands", "commands"),
             ("Keyboard shortcuts", "keys"), ("Moving from 2D to 3D", "2d3d"), ("What's New", "whatsnew"),
             ("Release Notes", "release"), ("API Help", "api"))

    def __init__(self, name="home", parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWHelpWindow")
        self.setWindowTitle("FreeCAD Help")
        self.resize(900, 620)
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("SWHelpSearch")
        self.search.setPlaceholderText("Search help")
        self.search.returnPressed.connect(lambda: self.find(self.search.text()))
        left.addWidget(self.search)
        self.contents = QtWidgets.QListWidget()
        self.contents.setObjectName("SWHelpContents")
        for text, key in self.PAGES:
            item = QtWidgets.QListWidgetItem(text)
            item.setData(Qt.UserRole, key)
            self.contents.addItem(item)
        self.contents.itemClicked.connect(lambda item: self.show_page(item.data(Qt.UserRole)))
        left.addWidget(self.contents, 1)
        lay.addLayout(left)
        self.view = QtWidgets.QTextBrowser()
        self.view.setObjectName("SWHelpView")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self.link)
        lay.addWidget(self.view, 3)
        self.current = None
        self.show_page(name)

    def show_page(self, name):
        self.current = name
        self._mark(name)
        if name.startswith("api:"):
            self.view.setHtml(api_page(name[4:]))
        else:
            self.view.setHtml(page(name))
        if name == "home" and news_wanted() and _NEWS["items"] is None:
            fetch_news(self._news_done)

    def _mark(self, name):
        """The contents row of the page on show is selected (a lesson marks Tutorials)."""
        key = "tutorials" if name.startswith("lesson") else "api" if name.startswith("api:") else \
            "commands" if name.startswith("cmd:") else name
        self.contents.blockSignals(True)
        self.contents.clearSelection()
        for r in range(self.contents.count()):
            item = self.contents.item(r)
            if item.data(Qt.UserRole) == key:
                self.contents.setCurrentItem(item)
                break
        self.contents.blockSignals(False)

    def _news_done(self):
        if alive(self) and self.current == "home":
            self.view.setHtml(page("home"))

    def link(self, url):
        text = url.toString()
        if text.startswith("fchelp:"):
            try:
                import Help
                Help.show(text[7:])
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: no FreeCAD help for %s (%s)\n" % (text[7:], error))
            return
        if text.startswith("guide:"):
            from . import helpguide
            page_, _hash, anchor = text[6:].partition("#")
            helpguide.show(page_, anchor)
            return
        if text.startswith("page:"):
            self.show_page(text[5:])
        elif text.startswith("api:"):
            self.show_page(text)
        elif text.startswith("run:"):
            run_key(text[4:])
        else:
            QtGui.QDesktopServices.openUrl(url)

    def find(self, text):
        """Search help: the pages and commands that mention the words."""
        words = [w.lower() for w in text.split() if w]
        if not words:
            return self.show_page("home")
        hits = []
        for title, key in self.PAGES:
            if key == "api":
                continue
            body = page(key)
            if all(w in body.lower() for w in words):
                hits.append("<li><a href='page:%s'>%s</a></li>" % (key, _esc(title)))
        cmds = []
        for _tab, rows in _commands():
            for k, label, tip, _s in rows:
                if all(w in (label + " " + tip).lower() for w in words):
                    cmds.append("<li><a href='page:cmd:%s'>%s</a>: %s</li>" % (k, _esc(label), _esc(tip)))
        self.current = "search"
        self.view.setHtml("<h2>Search: %s</h2><h3>Pages</h3><ul>%s</ul><h3>Commands</h3><ul>%s</ul>"
                          % (_esc(text), "".join(hits) or "<li>none</li>", "".join(cmds) or "<li>none</li>"))
        return len(hits) + len(cmds)


def run_key(key):
    """Run a CommandManager command by its catalog key (as its button does), or "cmd:<FreeCAD command>"."""
    if key.startswith("cmd:"):
        if Gui.Command.get(key[4:]) is not None:
            Gui.runCommand(key[4:], 0)
            return True
        return False
    try:
        from . import swmenus
        shell = swmenus._shell()
        if shell is not None:
            b = shell.binding(key)
            b.resolve()
            if b.implemented:
                b.run()
                return True
        from . import catalog
        for name in catalog.BY_KEY[key].natives:
            if Gui.Command.get(name) is not None:
                Gui.runCommand(name, 0)
                return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD Help: %s: %s\n" % (key, error))
    return False


_OPEN = []


def show(name="home", search=None):
    if use_web() and name == "home" and search is None:
        for cmd in ("Std_FreeCADUserHub", "Std_OnlineHelp"):
            if Gui.Command.get(cmd) is not None:
                Gui.runCommand(cmd, 0)
                return None
    box = HelpWindow(name)
    _OPEN[:] = [box]
    box.show()
    if search is not None:
        box.search.setFocus()
        if search:
            box.search.setText(search)
            box.find(search)
    return box


def pdf(name, title):
    """The page as a PDF in the temp folder, opened with the system's viewer."""
    doc = QtGui.QTextDocument()
    doc.setHtml(page(name))
    path = os.path.join(tempfile.gettempdir(), "FreeCAD-%s.pdf" % title.replace(" ", "-"))
    try:
        open(path, "ab").close()                # pkg321: still open (locked) in a PDF viewer: a new name
    except OSError:
        path = os.path.join(tempfile.gettempdir(), "FreeCAD-%s-%d.pdf" % (title.replace(" ", "-"), int(time.time() * 1000)))
    writer = QtGui.QPdfWriter(path)
    writer.setResolution(150)
    writer.setTitle("FreeCAD " + title)
    (doc.print_ if hasattr(doc, "print_") else doc.print)(writer)
    del writer
    if not os.environ.get("FREEWORKS_NO_OPEN"):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
    return path


# --------------------------------------------------------------------------- What's New > Interactive
class WhatsNewTour(QtWidgets.QDialog):
    """What's New > Interactive: one new thing at a time, with Show Me running it."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWWhatsNewTour")
        self.setWindowTitle("What's New")
        self.i = 0
        lay = QtWidgets.QVBoxLayout(self)
        self.title = QtWidgets.QLabel()
        f = self.title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        self.title.setFont(f)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.text, 1)
        row = QtWidgets.QHBoxLayout()
        self.prev = QtWidgets.QPushButton("< Previous")
        self.showme = QtWidgets.QPushButton("Show Me")
        self.next = QtWidgets.QPushButton("Next >")
        close = QtWidgets.QPushButton("Close")
        for b in (self.prev, self.showme, self.next, close):
            row.addWidget(b)
        lay.addLayout(row)
        self.prev.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(1))
        self.showme.clicked.connect(lambda: run_key(WHATS_NEW[self.i][2]) if WHATS_NEW[self.i][2] else None)
        close.clicked.connect(self.close)
        self.resize(460, 200)
        self.go(0)

    def go(self, step):
        self.i = max(0, min(len(WHATS_NEW) - 1, self.i + step))
        t, d, k = WHATS_NEW[self.i]
        self.title.setText("%d of %d: %s" % (self.i + 1, len(WHATS_NEW), t))
        self.text.setText(d)
        self.prev.setEnabled(self.i > 0)
        self.next.setEnabled(self.i < len(WHATS_NEW) - 1)
        self.showme.setEnabled(bool(k))



def diagnostics():
    """[(name, value)]: what a support question needs to know."""
    rows = [("Add-on", version()), ("FreeCAD", freecad_version()), ("Python", sys.version.split()[0]),
            ("Qt", QtCore.qVersion()), ("System", "%s %s (%s)" % (platform.system(), platform.release(), platform.machine())),
            ("Add-on folder", str(paths.ADDON_DIR))]
    try:
        from PySide import QtOpenGL  # noqa: F401
        ctx = QtGui.QOpenGLContext.currentContext()
        rows.append(("OpenGL", "%d.%d" % ctx.format().version() if ctx is not None else "(no current context)"))
    except Exception as _fw_err:
        _fw_log("helpmenu.py:604", _fw_err)
    try:
        mods = sorted(d for d in os.listdir(os.path.join(App.getUserAppDataDir(), "Mod")) if not d.startswith("."))
        rows.append(("Add-ons", ", ".join(mods)))
    except Exception as _fw_err:
        _fw_log("helpmenu.py:609", _fw_err)
    doc = App.ActiveDocument
    if doc is not None:
        rows.append(("Active document", "%s (%d objects)" % (doc.Label, len(doc.Objects))))
    return rows


def time_rebuild(doc=None):
    """Seconds a full rebuild of the document takes (Ctrl+Q's force rebuild)."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    for o in doc.Objects:
        o.touch()
    t = time.perf_counter()
    doc.recompute()
    return time.perf_counter() - t


def rx_folder():
    path = os.path.join(App.getUserAppDataDir(), "Rx")
    os.makedirs(path, exist_ok=True)
    return path


def report_view_text():
    """What the Report view shows now ("" when it is not there)."""
    try:
        mw = Gui.getMainWindow()
        for w in mw.findChildren(QtWidgets.QTextEdit) + mw.findChildren(QtWidgets.QPlainTextEdit):
            if w.objectName() == "Report view" or (w.parent() is not None and w.parent().objectName() == "Report view"):
                return w.toPlainText()
    except Exception as _fw_err:
        _fw_log("helpmenu.py:report_view_text", _fw_err)
    return ""


def log_files():
    """[(what, path)] of the files support asks for: the settings, the log, crash reports, Rx packages."""
    out = []
    for what, path in (("User settings", os.path.join(App.getUserConfigDir(), "user.cfg")),
                       ("System settings", os.path.join(App.getUserConfigDir(), "system.cfg")),
                       ("Log file", App.ConfigGet("LoggingFileName") or "")):
        if path and os.path.isfile(path):
            out.append((what, path))
    for folder, what in ((App.getUserAppDataDir(), "Crash report"), (App.getTempPath(), "Crash report"),
                         (rx_folder(), "Rx package")):
        try:
            for f in sorted(os.listdir(folder)):
                full = os.path.join(folder, f)
                if os.path.isfile(full) and (f.endswith((".dmp", "crash.log")) if what == "Crash report"
                                             else f.endswith(".zip")):
                    out.append((what, full))
        except OSError as _fw_err:
            _fw_log("helpmenu.py:log_files", _fw_err)
    return out


def capture(description, include_document=False, include_settings=False, folder=None):
    """Problem Capture: a zip with the description, the diagnostics, the Report view and (when ticked)
    the active document and user.cfg, for a support question. Returns the zip's path."""
    import zipfile
    folder = folder or rx_folder()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "FreeCAD-Rx-%s.zip" % time.strftime("%Y%m%d-%H%M%S"))
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, "FreeCAD-Rx-%s-%d.zip" % (time.strftime("%Y%m%d-%H%M%S"), n))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Description.txt", description or "")
        z.writestr("Diagnostics.txt", "\n".join("%s: %s" % (a, b) for a, b in diagnostics()))
        z.writestr("Report view.txt", report_view_text())
        doc = App.ActiveDocument
        if include_document and doc is not None:
            name = os.path.basename(doc.FileName) if doc.FileName else (doc.Name + ".FCStd")
            tmp = os.path.join(tempfile.mkdtemp(prefix="fwrx"), name)
            doc.saveCopy(tmp)
            z.write(tmp, "Document/" + name)
        if include_settings:
            cfg = os.path.join(App.getUserConfigDir(), "user.cfg")
            if os.path.isfile(cfg):
                z.write(cfg, "Settings/user.cfg")
    return path


def addins(root=None):
    """[(folder name, path, enabled)] of the add-ons in the user's Mod folder."""
    root = root or os.path.join(App.getUserAppDataDir(), "Mod")
    out = []
    try:
        for d in sorted(os.listdir(root), key=str.lower):
            full = os.path.join(root, d)
            if os.path.isdir(full) and not d.startswith((".", "__")):
                out.append((d, full, not os.path.exists(os.path.join(full, "ADDON_DISABLED"))))
    except OSError as _fw_err:
        _fw_log("helpmenu.py:addins", _fw_err)
    return out


def set_addin(path, enabled):
    """Enable or disable an add-on at the next start, as the Addon Manager does (its ADDON_DISABLED marker)."""
    mark = os.path.join(path, "ADDON_DISABLED")
    if enabled and os.path.isfile(mark):
        os.remove(mark)
    elif not enabled and not os.path.exists(mark):
        with open(mark, "w") as f:
            f.write("Disabled from FreeCAD Rx\n")
    return not os.path.exists(mark)


def old_temp_files(days=1.0, folder=None):
    """[(path, bytes)] of FreeCAD's own temp files older than the days given. Only loose files in FreeCAD's
    temp folder: the folders of open documents (and their recovery data) are never touched."""
    folder = folder or App.getTempPath()
    limit = time.time() - days * 86400
    out = []
    try:
        for f in os.listdir(folder):
            full = os.path.join(folder, f)
            if os.path.isfile(full) and not os.path.islink(full) and os.path.getmtime(full) < limit:
                out.append((full, os.path.getsize(full)))
    except OSError as _fw_err:
        _fw_log("helpmenu.py:old_temp_files", _fw_err)
    return sorted(out)


def clean_temp(files):
    """Remove the files listed (from old_temp_files); a file in use stays. Returns (removed, bytes)."""
    n = size = 0
    for path, b in files:
        try:
            os.remove(path)
            n += 1
            size += b
        except OSError as _fw_err:
            _fw_log("helpmenu.py:clean_temp", _fw_err)
    return n, size


def benchmark(view=None):
    """{"CPU": s, "Graphics": s, "Disk": s}: a boolean-heavy shape build, 30 redraws of the 3D view, and a
    32 MB write and read in the temp folder. Lower is faster."""
    import Part
    out = {}
    t = time.perf_counter()
    shape = Part.makeBox(100, 100, 20)
    for i in range(12):
        for j in range(4):
            shape = shape.cut(Part.makeCylinder(2.5, 20, App.Vector(6 + i * 8, 10 + j * 25, 0)))
    shape = shape.makeFillet(1.0, shape.Edges[:12])
    shape.tessellate(0.05)
    out["CPU"] = time.perf_counter() - t
    try:
        view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None)
        if view is not None and hasattr(view, "redraw"):
            t = time.perf_counter()
            for _i in range(30):
                view.redraw()
                QtWidgets.QApplication.processEvents()
            out["Graphics"] = time.perf_counter() - t
        else:
            out["Graphics"] = None
    except Exception as _fw_err:
        _fw_log("helpmenu.py:benchmark", _fw_err)
        out["Graphics"] = None
    path = os.path.join(tempfile.gettempdir(), "fw-rx-bench.bin")
    t = time.perf_counter()
    block = os.urandom(1 << 20)
    with open(path, "wb") as f:
        for _i in range(32):
            f.write(block)
        f.flush()
        os.fsync(f.fileno())
    with open(path, "rb") as f:
        while f.read(1 << 20):
            pass
    out["Disk"] = time.perf_counter() - t
    try:
        os.remove(path)          # the benchmark's own file
    except OSError as _fw_err:
        _fw_log("helpmenu.py:benchmark", _fw_err)
    return out


def _open_folder(path):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


class RxDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWRx")
        self.setWindowTitle("FreeCAD Rx")
        self.resize(680, 480)
        lay = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        tabs.setObjectName("SWRxTabs")
        self.tabs = tabs
        lay.addWidget(tabs, 1)
        # Problem Capture
        cap = QtWidgets.QWidget()
        cl = QtWidgets.QVBoxLayout(cap)
        cl.addWidget(QtWidgets.QLabel("Describe the problem and the steps that lead to it:"))
        self.description = QtWidgets.QPlainTextEdit()
        self.description.setObjectName("SWRxDescription")
        cl.addWidget(self.description, 1)
        self.with_doc = QtWidgets.QCheckBox("Include the active document")
        self.with_doc.setObjectName("SWRxIncludeDocument")
        self.with_cfg = QtWidgets.QCheckBox("Include my settings (user.cfg)")
        self.with_cfg.setObjectName("SWRxIncludeSettings")
        cl.addWidget(self.with_doc)
        cl.addWidget(self.with_cfg)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Package Files")
        b.setObjectName("SWRxPackage")
        b.clicked.connect(lambda *_a: self.package())
        row.addWidget(b)
        row.addStretch(1)
        cl.addLayout(row)
        self.captured = QtWidgets.QLabel("")
        self.captured.setObjectName("SWRxCaptured")
        self.captured.setWordWrap(True)
        self.captured.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        cl.addWidget(self.captured)
        tabs.addTab(cap, "Problem Capture")
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Item", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        for name, val in diagnostics():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(val)))
        tabs.addTab(self.table, "Diagnostics")
        perf = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(perf)
        self.perf = QtWidgets.QLabel("Times a full rebuild of the active document.")
        run = QtWidgets.QPushButton("Run Rebuild Test")
        run.clicked.connect(self.rebuild_test)
        pl.addWidget(self.perf)
        pl.addWidget(run)
        pl.addStretch(1)
        tabs.addTab(perf, "Performance")
        # Files and Logs
        fl = QtWidgets.QWidget()
        fll = QtWidgets.QVBoxLayout(fl)
        self.files = QtWidgets.QTableWidget(0, 2)
        self.files.setObjectName("SWRxFiles")
        self.files.setHorizontalHeaderLabels(["File", "Path"])
        self.files.horizontalHeader().setStretchLastSection(True)
        self.files.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.files.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        fll.addWidget(self.files, 1)
        row = QtWidgets.QHBoxLayout()
        for text, name, fn in (("Open Containing Folder", "SWRxOpenFolder", self.open_file_folder),
                               ("Refresh", "SWRxRefreshFiles", self.fill_files)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(lambda *_a, fn=fn: fn())
            row.addWidget(b)
        row.addStretch(1)
        fll.addLayout(row)
        tabs.addTab(fl, "Files and Logs")
        # System Maintenance
        sm = QtWidgets.QWidget()
        sml = QtWidgets.QVBoxLayout(sm)
        sml.addWidget(QtWidgets.QLabel("FreeCAD's temp files older than a day. Open documents' folders "
                                       "and recovery data are never touched."))
        self.temp_note = QtWidgets.QLabel("")
        self.temp_note.setObjectName("SWRxTempNote")
        sml.addWidget(self.temp_note)
        row = QtWidgets.QHBoxLayout()
        for text, name, fn in (("Check", "SWRxCheckTemp", self.check_temp), ("Clean Up Now", "SWRxCleanTemp", self.clean_temp)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(lambda *_a, fn=fn: fn())
            row.addWidget(b)
        row.addStretch(1)
        sml.addLayout(row)
        sml.addStretch(1)
        tabs.addTab(sm, "System Maintenance")
        # Add-ins
        ad = QtWidgets.QWidget()
        adl = QtWidgets.QVBoxLayout(ad)
        adl.addWidget(QtWidgets.QLabel("Untick an add-on to leave it out at the next start of FreeCAD."))
        self.addins = QtWidgets.QTableWidget(0, 2)
        self.addins.setObjectName("SWRxAddins")
        self.addins.setHorizontalHeaderLabels(["Add-on", "Folder"])
        self.addins.horizontalHeader().setStretchLastSection(True)
        self.addins.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.addins.itemChanged.connect(self._addin_ticked)
        adl.addWidget(self.addins, 1)
        self.addin_note = QtWidgets.QLabel("")
        self.addin_note.setObjectName("SWRxAddinNote")
        adl.addWidget(self.addin_note)
        tabs.addTab(ad, "Add-ins")
        # Benchmark
        bm = QtWidgets.QWidget()
        bml = QtWidgets.QVBoxLayout(bm)
        bml.addWidget(QtWidgets.QLabel("Times this computer on a shape build (CPU), 30 redraws of the 3D view "
                                       "(graphics) and a 32 MB file (disk). Lower is faster."))
        self.bench = QtWidgets.QLabel("")
        self.bench.setObjectName("SWRxBenchmark")
        bml.addWidget(self.bench)
        b = QtWidgets.QPushButton("Run Benchmark")
        b.setObjectName("SWRxRunBenchmark")
        b.clicked.connect(lambda *_a: self.run_benchmark())
        bml.addWidget(b)
        bml.addStretch(1)
        tabs.addTab(bm, "Benchmark")
        self.fill_files()
        self.fill_addins()
        row = QtWidgets.QHBoxLayout()
        copy = QtWidgets.QPushButton("Copy to Clipboard")
        copy.clicked.connect(self.copy)
        report = QtWidgets.QPushButton("Report an Issue")
        report.clicked.connect(lambda: Gui.runCommand("Std_ReportBug", 0) if Gui.Command.get("Std_ReportBug") else None)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        for b in (copy, report, close):
            row.addWidget(b)
        lay.addLayout(row)

    def text(self):
        return "\n".join("%s: %s" % (self.table.item(r, 0).text(), self.table.item(r, 1).text())
                         for r in range(self.table.rowCount()))

    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.text())

    def rebuild_test(self):
        s = time_rebuild()
        self.perf.setText("No document open." if s is None else "Full rebuild: %.3f s" % s)
        return s

    def package(self, folder=None):
        path = capture(self.description.toPlainText(), self.with_doc.isChecked(), self.with_cfg.isChecked(), folder)
        self.captured.setText("Packaged: %s" % path)
        self.fill_files()
        return path

    def fill_files(self):
        self.files.setRowCount(0)
        for what, path in log_files():
            r = self.files.rowCount()
            self.files.insertRow(r)
            self.files.setItem(r, 0, QtWidgets.QTableWidgetItem(what))
            self.files.setItem(r, 1, QtWidgets.QTableWidgetItem(path))

    def open_file_folder(self):
        r = self.files.currentRow()
        if r < 0:
            r = 0 if self.files.rowCount() else -1
        if r < 0:
            return None
        folder = os.path.dirname(self.files.item(r, 1).text())
        _open_folder(folder)
        return folder

    def check_temp(self, folder=None):
        self._temp = old_temp_files(folder=folder)
        mb = sum(b for _p, b in self._temp) / 1048576.0
        self.temp_note.setText("%d old temp files, %.1f MB." % (len(self._temp), mb) if self._temp
                               else "No old temp files.")
        return self._temp

    def clean_temp(self, folder=None, ask=True):
        files = self.check_temp(folder)
        if not files:
            return (0, 0)
        if ask and QtWidgets.QMessageBox.question(
                self, "System Maintenance", "Remove %d of FreeCAD's old temp files?" % len(files),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return None
        n, size = clean_temp(files)
        self.temp_note.setText("Removed %d files, %.1f MB." % (n, size / 1048576.0))
        return (n, size)

    def fill_addins(self, root=None):
        self.addins.blockSignals(True)
        self.addins.setRowCount(0)
        here = os.path.normcase(os.path.realpath(str(paths.ADDON_DIR)))
        for name, path, on in addins(root):
            r = self.addins.rowCount()
            self.addins.insertRow(r)
            it = QtWidgets.QTableWidgetItem(name)
            it.setData(QtCore.Qt.UserRole, path)
            if os.path.normcase(os.path.realpath(path)) == here:
                it.setToolTip("This interface; turn it off from the Addon Manager.")
            else:
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
            self.addins.setItem(r, 0, it)
            self.addins.setItem(r, 1, QtWidgets.QTableWidgetItem(path))
        self.addins.blockSignals(False)

    def _addin_ticked(self, item):
        if item.column() != 0 or not (item.flags() & QtCore.Qt.ItemIsUserCheckable):
            return
        on = set_addin(item.data(QtCore.Qt.UserRole), item.checkState() == QtCore.Qt.Checked)
        self.addin_note.setText("%s %s at the next start of FreeCAD." % (item.text(), "loads" if on else "is left out"))

    def run_benchmark(self):
        r = benchmark()
        self.bench.setText("   ".join("%s: %s" % (k, "-" if v is None else "%.2f s" % v) for k, v in r.items()))
        return r


# --------------------------------------------------------------------------- About
class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWAboutFreeWorks")
        self.setWindowTitle("About FreeCAD")
        lay = QtWidgets.QVBoxLayout(self)
        t = QtWidgets.QLabel("<h2>FreeCAD interface %s</h2><p>A feature-based CAD look and workflow for FreeCAD %s.</p>"
                             "<p>Licensed under the LGPL 2.1 or later. It runs on FreeCAD, which is "
                             "made by the FreeCAD contributors.</p>" % (version(), freecad_version()))
        t.setWordWrap(True)
        lay.addWidget(t)
        row = QtWidgets.QHBoxLayout()
        fc = QtWidgets.QPushButton("About FreeCAD...")
        fc.clicked.connect(lambda: Gui.runCommand("Std_About", 0))
        ok = QtWidgets.QPushButton("OK")
        ok.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(fc)
        row.addWidget(ok)
        lay.addLayout(row)


def _keep(box):
    _OPEN[:] = [box]
    box.show()
    return box


# --------------------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, menu, tip, run, checkable=False):
        self.menu, self.tip, self.run, self.checkable = menu, tip, run, checkable

    def GetResources(self):
        r = {"MenuText": self.menu, "ToolTip": self.tip}
        if self.checkable:
            r["Checkable"] = use_web()
        return r

    def Activated(self, checked=None):
        if self.checkable:
            set_use_web(bool(checked) if checked is not None else not use_web())
            return
        self.run()

    def IsActive(self):
        return True


COMMUNITY = "https://forum.freecad.org/search.php?keywords=%s"
opened = []                 # the community searches opened, for checks


def community_url(text):
    return COMMUNITY % bytes(QtCore.QUrl.toPercentEncoding(text.strip())).decode()


def search_community(text=None):
    """Help > Search > Community: the words you type, searched on the FreeCAD forum."""
    if text is None:
        text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Search Community",
                                                  "Search the FreeCAD community for:")
        if not ok:
            return None
    if not text.strip():
        return None
    url = community_url(text)
    opened.append(url)
    if App.GuiUp and not os.environ.get("FREEWORKS_NO_BROWSER"):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
    return url


COMMANDS = {
    "SWStyle_Help": ("Help", "FreeCAD Help (on this computer; Use Web Help opens FreeCAD's online help)",
                     lambda: show("home")),
    "SWStyle_Tutorials": ("Tutorials", "Step-by-step lessons", lambda: show("tutorials")),
    "SWStyle_APIHelp": ("API Help", "The FreeCAD Python modules for macros", lambda: show("api")),
    "SWStyle_UseWebHelp": ("Use Web Help", "Help opens FreeCAD's online help instead of the built-in Help", None),
    "SWStyle_HelpSearchHelp": ("Help", "Search FreeCAD Help", lambda: show("home", search="")),
    "SWStyle_SearchCommunity": ("Community", "Search the FreeCAD community forum", lambda: search_community()),
    "SWStyle_ReleaseNotes": ("Release Notes", "What this FreeCAD release changes", lambda: show("release")),
    "SWStyle_WhatsNewHTML": ("HTML", "What's New, in the help window", lambda: show("whatsnew")),
    "SWStyle_WhatsNewPDF": ("PDF", "What's New, as a PDF", lambda: pdf("whatsnew", "Whats New")),
    "SWStyle_WhatsNewInteractive": ("Interactive", "What's New, one thing at a time", lambda: _keep(WhatsNewTour())),
    "SWStyle_IntroducingPDF": ("Introducing FreeCAD (pdf)", "A short introduction, as a PDF", lambda: pdf("intro", "Introducing")),
    "SWStyle_2Dto3D": ("Moving from 2D to 3D", "For 2D drafters", lambda: show("2d3d")),
    "SWStyle_Rx": ("FreeCAD Rx", "Diagnostics for support questions", lambda: _keep(RxDialog())),
    "SWStyle_AboutFreeWorks": ("About FreeCAD...", "Version and licence", lambda: _keep(AboutDialog())),
}


def register():
    for name, (menu, tip, run) in COMMANDS.items():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(menu, tip, run, checkable=name == "SWStyle_UseWebHelp"))
    try:
        from . import checkstate        # the menu ticks Use Web Help from the setting itself
        checkstate.register("SWStyle_UseWebHelp", use_web)
    except Exception as _fw_err:
        _fw_log("helpmenu.py:780", _fw_err)
