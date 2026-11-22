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
from PySide import QtCore

HIDDEN_LINE = 3         # Std_DrawStyle: 0 As is, 1 Points, 2 Wireframe, 3 Hidden line, ...
NO_SHADING = 4          # the style both HLR and HLV sit on
DASH = 0x0F0F
PHANTOM = 0xFF33        # tangent edges As phantom: a long dash and two short ones (displayextras)
FLAT_LINES = 6
SHADED = 5              # Std_DrawStyle Shaded: drawn here as Flat lines with the edges unseen ("shd")


def _option(key, default):
    """System Options > Display: Hidden edges displayed as (Solid/Dashed), Edge display in shaded with
    edges mode (HLR/Wireframe)."""
    try:
        from . import optionspages
        return optionspages.stored("Radio", key, default)
    except Exception as _fw_err:
        _fw_log("hlv.py:48", _fw_err)
        return default
BLACK = (0.0, 0.0, 0.0)
WHITE = (1.0, 1.0, 1.0)
DARK_EDGE = (0.88, 0.88, 0.9)       # the drawn edges on a Dark viewport (black would vanish on it)
DARK_HIDDEN = (0.6, 0.6, 0.64)
WIREFRAME = 2                       # Std_DrawStyle Wireframe
LINKS = ("App::Link", "Assembly::AssemblyLink")
_GL_COLOR_MASK = []
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/View"
DRAFT_KEY = "DraftQualityHLR"
FINE, DRAFT = 0.05, 1.0       # edge deflection, in % of the part's size
GREY = (0.45, 0.45, 0.45)
SKIP = ("Part::Part2DObject", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
        "PartDesign::CoordinateSystem", "App::Origin")


def _parents_shown(obj):
    """A hidden Body (or App::Part) hides its features even though they keep Visibility on."""
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None:
        if not parent.Visibility:
            return False
        parent = parent.getParentGeoFeatureGroup()
    return True


def _gone(doc):
    """extapps/68: the solids hidden on Solid Bodies rows, read once for a whole pass (it was read once per
    shape, and each read walks every object: 200 parts, 40,000 object visits a pass)."""
    try:
        from . import multibody
        if "gone" not in multibody.without_hidden.__code__.co_varnames:
            return None
        return multibody.hidden_solids(doc)
    except Exception:
        return None


def _dark():
    try:
        from . import style
        return style.dark()
    except Exception:
        return False


def _edge_rgb():
    return DARK_EDGE if _dark() else BLACK


def _hidden_rgb():
    return DARK_HIDDEN if _dark() else GREY


def _colour_writes(on):
    """glColorMask for the whole scene's colour, through the GL library lightterms already loads."""
    try:
        if not _GL_COLOR_MASK:
            from . import lightterms
            lib = lightterms._library()
            fn = getattr(lib, "glColorMask", None) if lib is not None else None
            if fn is not None:
                import ctypes
                fn.argtypes = [ctypes.c_ubyte] * 4
            _GL_COLOR_MASK.append(fn)
        fn = _GL_COLOR_MASK[0]
        if fn is not None:
            v = 1 if on else 0
            fn(v, v, v, v)
    except Exception as _fw_err:
        _fw_log("hlv.py:colormask", _fw_err)


def _mask_callback(on):
    """A scene node that turns the colour writes off (or back on) as the scene draws."""
    from pivy import coin
    cb = coin.SoCallback()

    def call(data, action, on=on):
        try:
            if action.isOfType(coin.SoGLRenderAction.getClassTypeId()):
                _colour_writes(on)
        except Exception as _fw_err:
            _fw_log("hlv.py:maskcb", _fw_err)
    cb.setCallback(call)
    cb._fw_call = call          # kept alive with the node
    return cb


def _private_linked(link):
    """The part a component draws, when nothing but links shows it: hidden in its own document, or
    in a document with no 3D window of its own. None otherwise (its window would lose its edges)."""
    try:
        linked = link.getLinkedObject(True)
        if linked is None or linked is link or linked.ViewObject is None:
            return None
        if linked.Document is not link.Document:
            gdoc = Gui.getDocument(linked.Document.Name)
            if gdoc is not None and gdoc.mdiViewsOfType("Gui::View3DInventor"):
                return None if linked.Visibility else linked
            return linked
        return None if linked.Visibility else linked
    except Exception:
        return None


def _component(obj):
    """A shown component of an assembly (a link at the top of its document's assembly, not one inside
    a subassembly's link, which draws through that link)."""
    if obj.TypeId not in LINKS and not obj.isDerivedFrom("App::Link"):
        return False
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None:
        if parent.TypeId in LINKS:
            return False
        parent = parent.getParentGeoFeatureGroup()
    return True


def _link_shape(obj):
    """A component's shape where it shows (its own placement and its assembly's)."""
    import Part
    if obj.ViewObject is None or not obj.ViewObject.isVisible() or not _parents_shown(obj):
        return None
    shape = Part.getShape(obj)
    if shape is None or shape.isNull():
        return None
    parent = obj.getParentGeoFeatureGroup()
    if parent is not None:
        shape = shape.transformed(parent.getGlobalPlacement().toMatrix())
    return shape


def has_links(doc):
    try:
        return any(_component(o) for o in doc.Objects)
    except Exception:
        return False


def _shapes(doc):
    """Global shapes of what is shown: tips of bodies and plain Part features, not sketches or datums,
    and an assembly's components."""
    import Part
    out = []
    gone = _gone(doc)
    for obj in doc.Objects:
        try:
            if _component(obj):
                shape = _link_shape(obj)
                if shape is not None and _has_edges(shape):
                    out.append(shape)
                continue
            if obj.TypeId in ("PartDesign::Body", "App::Part") or not obj.isDerivedFrom("Part::Feature"):
                continue
            if any(obj.isDerivedFrom(t) for t in SKIP):
                continue
            if obj.ViewObject is None or not obj.ViewObject.isVisible() or not _parents_shown(obj):
                continue
            shape = _shown_part(doc, Part.getShape(obj), gone)
        except Exception as _fw_err:
            _fw_log("hlv.py:84", _fw_err)
            continue
        if shape is not None and not shape.isNull() and _has_edges(shape):
            out.append(shape)
    return out


def _has_edges(shape):
    """shape.Edges built a Python edge for every edge only to be tested: 150 ms of the 185 this walk
    took on a 300-part assembly, at each show, hide or move (vd121, 11-21). Counted in C++ instead."""
    try:
        return shape.countElement("Edge") > 0
    except Exception:
        return bool(shape.Edges)


def _shown_part(doc, shape, gone=None):
    """shape without the solids hidden on their Solid Bodies rows (multibody, features/349), None when
    all are: a hidden body gets no hidden-line drawing either."""
    try:
        from . import multibody
        fn = getattr(multibody, "without_hidden", None)
        if fn is None:
            return shape
        return fn(doc, shape, gone) if gone is not None else fn(doc, shape)
    except Exception as _fw_err:
        _fw_log("hlv.py:99", _fw_err)
        return shape


def _seams(shape):
    ""


    try:
        from . import displayextras
        if not displayextras.seams_hidden():
            return set()
        return set(displayextras.seam_edges(shape))
    except Exception as _fw_err:
        _fw_log("hlv seams", _fw_err)
        return set()


_SMOOTH = []        # [(edge count, shape, smooth edge indices)]: an assembly's links of one part share it


def _tangent():
    try:
        from . import displayextras
        return displayextras.tangent_mode()
    except Exception as _fw_err:
        _fw_log("hlv tangent", _fw_err)
        return "Visible"


def _smooth(shape):
    """Indices of the shape's tangent edges (System Options > Display, Part/Assembly tangent edge display)."""
    try:
        from . import displayextras
        count = shape.countElement("Edge")
        for n, held, got in _SMOOTH:
            if n == count and held.isPartner(shape):
                return got
        got = set(displayextras.smooth_edges(shape))
        _SMOOTH.append((count, shape, got))
        del _SMOOTH[:-64]
        return got
    except Exception as _fw_err:
        _fw_log("hlv smooth", _fw_err)
        return set()


def polylines(shapes, deflection=0.05, phantom=None):
    ""


    lines = []
    mode = _tangent() if phantom is not None else "Visible"
    for shape in shapes:
        size = max(shape.BoundBox.DiagonalLength, 1.0)
        seams = _seams(shape)
        smooth = _smooth(shape) if mode != "Visible" else ()
        for i, edge in enumerate(shape.Edges):
            if i in seams or (i in smooth and mode != "Phantom"):
                continue
            into = phantom if i in smooth else lines
            try:
                pts = edge.discretize(Deflection=deflection * size / 100.0)
            except Exception as _fw_err:
                _fw_log("hlv.py:112", _fw_err)
                continue
            if len(pts) >= 2:
                into.append(pts)
    return lines


def keyed_polylines(doc, deflection=0.05):
    """{(object name, "EdgeN"): points} for every edge of the shown shapes (the selection highlight)."""
    import Part
    out = {}
    for obj in doc.Objects:
        try:
            if obj.TypeId in ("PartDesign::Body", "App::Part") or not obj.isDerivedFrom("Part::Feature"):
                continue
            if any(obj.isDerivedFrom(t) for t in SKIP):
                continue
            if obj.ViewObject is None or not obj.ViewObject.isVisible() or not _parents_shown(obj):
                continue
            shape = Part.getShape(obj)
        except Exception as _fw_err:
            _fw_log("hlv.py:133", _fw_err)
            continue
        if shape is None or shape.isNull():
            continue
        shown = _shown_part(doc, shape)
        if shown is None:
            continue
        keep = None if shown is shape else shown.Edges
        size = max(shape.BoundBox.DiagonalLength, 1.0)
        seams = _seams(shape)
        for i, edge in enumerate(shape.Edges):
            if i in seams:
                continue
            if keep is not None and not any(edge.isPartner(k) for k in keep):
                continue
            try:
                pts = edge.discretize(Deflection=deflection * size / 100.0)
            except Exception as _fw_err:
                _fw_log("hlv.py:148", _fw_err)
                continue
            if len(pts) >= 2:
                out[(obj.Name, "Edge%d" % (i + 1))] = pts
    return out


def _colour(key, default):
    value = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(key, default)
    return ((value >> 24) & 255) / 255.0, ((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0


def _edge_key(doc_name, obj_name, sub):
    """(leaf object name, "EdgeN") of a picked or hovered edge, else None."""
    element = (sub or "").split(".")[-1]
    if not element.startswith("Edge"):
        return None
    try:
        obj = App.getDocument(doc_name).getObject(obj_name)
        if "." in sub:
            leaf = obj.getSubObject(sub, retType=1)
            obj = leaf if leaf is not None else obj
        return obj.Name, element
    except Exception as _fw_err:
        _fw_log("hlv.py:172", _fw_err)
        return None


class _HiddenEdges:
    def __init__(self):
        self.on = False         # Hidden Lines Visible (hidden edges dashed)
        self.mode = None        # None, "hlr" or "hlv"
        self.node = None
        self.prefix = None      # the white override ahead of the model
        self.prefix_parent = None   # the separator that wraps it with FreeCAD's ObjectGroup
        self.scene = None
        self.doc_name = None
        self.view = None
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.draw)
        self.hooked = []
        self.keyed = {}         # (object, "EdgeN") -> points, for the highlight
        self.hl = None          # the selected / hovered edges, drawn over the black ones
        self.hl_timer = QtCore.QTimer()
        self.hl_timer.setSingleShot(True)
        self.hl_timer.setInterval(0)
        self.hl_timer.timeout.connect(self.highlight)
        self.modes = {}

    def set(self, on):
        """on: True = Hidden Lines Visible, "hlr" = Hidden Lines Removed, False/None = off."""
        mode = "hlv" if on is True else (on if on in ("hlr", "hlv", "swe", "shd", "wf") else None)
        self.mode = mode
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is not None:
                if mode:
                    self.modes[gdoc.Document.Name] = mode
                else:
                    self.modes.pop(gdoc.Document.Name, None)
        except Exception as _fw_err:
            _fw_log("hlv.py:modes", _fw_err)
        self.on = mode == "hlv"
        if mode:
            self._hook_styles()
            self._hook_theme()
            self.draw()
        else:
            self.clear()

    def later(self):
        if self.mode:
            self.timer.start()

    def clear(self):
        if self.view is not None and self._alive():
            scene = self.scene
            try:
                if self.node is not None:
                    scene.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("hlv.py:212", _fw_err)
            try:
                # put FreeCAD's ObjectGroup back where the wrapper stood
                wrap = self.prefix_parent
                if wrap is not None:
                    i = scene.findChild(wrap)
                    if i >= 0 and wrap.getNumChildren() > 1:
                        group = wrap.getChild(1)
                        scene.replaceChild(i, group)
                        group.unref()           # the ref() taken in draw()
            except Exception as _fw_err:
                _fw_log("hlv.py:223", _fw_err)
        wrap = getattr(self, "sec_wrap", None)
        self.sec_wrap = None
        if wrap is not None:
            try:
                sroot, cwrap, caps = wrap
                k = sroot.findChild(cwrap)
                if k >= 0:
                    sroot.replaceChild(k, caps)
                caps.unref()
            except Exception as _fw_err:
                _fw_log("hlv.py:section-unwrap", _fw_err)
        self._unhush()
        self.node = self.prefix = self.prefix_parent = self.view = self.scene = self.hl = None
        self.doc_name = None

    def _hush(self, doc):
        ""



        from pivy import coin
        self.hushed = getattr(self, "hushed", [])
        self.link_hush = getattr(self, "link_hush", [])
        done = set()
        for obj in doc.Objects:
            try:
                if _component(obj) and obj.ViewObject is not None:
                    linked = _private_linked(obj)
                    if linked is not None:
                        # the part draws only through links here: its own edge styles go invisible
                        key = (linked.Document.Name, linked.Name)
                        if key not in done:
                            done.add(key)
                            self._hush_nodes(linked.ViewObject.RootNode)
                        continue
                    # a component draws its part's own scene, shared with the part's window: a line
                    # style ahead of it, in the link's own node, quiets the edges through this link only
                    root = obj.ViewObject.RootNode
                    quiet = coin.SoDrawStyle()
                    quiet.setName("SWShadedLinkEdges")
                    quiet.linePattern = 0
                    for field in (quiet.style, quiet.lineWidth, quiet.pointSize):
                        field.setIgnored(True)
                    quiet.setOverride(True)
                    root.insertChild(quiet, 0)
                    self.link_hush.append((root, quiet))
                    continue
                if obj.TypeId in ("PartDesign::Body", "App::Part") or not obj.isDerivedFrom("Part::Feature"):
                    continue
                if any(obj.isDerivedFrom(t) for t in SKIP) or obj.ViewObject is None:
                    continue
                self._hush_nodes(obj.ViewObject.RootNode)
            except Exception as _fw_err:
                _fw_log("hlv.py:hush", _fw_err)

    def _hush_nodes(self, root):
        from pivy import coin
        seen = set()
        for kind in ("SoBrepEdgeSet", "SoBrepPointSet"):
            search = coin.SoSearchAction()
            search.setType(coin.SoType.fromName(kind))
            search.setInterest(coin.SoSearchAction.ALL)
            search.apply(root)
            for k in range(search.getPaths().getLength()):
                path = search.getPaths()[k]
                if path.getLength() < 2:
                    continue
                parent = path.getNodeFromTail(1)
                for c in range(parent.getNumChildren()):
                    node = parent.getChild(c)
                    if not node.isOfType(coin.SoDrawStyle.getClassTypeId()):
                        continue
                    ident = int(node.this) if hasattr(node, "this") else id(node)
                    if ident in seen:
                        continue
                    seen.add(ident)
                    f = node.style
                    if f.getValue() != coin.SoDrawStyle.INVISIBLE:
                        self.hushed.append((node, "style", f.getValue(), coin.SoDrawStyle.INVISIBLE))
                        f.setValue(coin.SoDrawStyle.INVISIBLE)

    def _unhush(self):
        for root, node in getattr(self, "link_hush", []):
            try:
                i = root.findChild(node)
                if i >= 0:
                    root.removeChild(i)
            except Exception as _fw_err:
                _fw_log("hlv.py:unhushlink", _fw_err)
        self.link_hush = []
        for node, field, old, value in getattr(self, "hushed", []):
            try:
                f = getattr(node, field)
                if f.getValue() == value:
                    f.setValue(old)
            except Exception as _fw_err:
                _fw_log("hlv.py:unhush", _fw_err)
        self.hushed = []

    def _alive(self):
        """The view drawn in is still open (a closed document's scene nodes are gone: touching them
        crashed FreeCAD)."""
        try:
            if self.doc_name not in App.listDocuments():
                return False
            gdoc = Gui.getDocument(self.doc_name)
            me = getattr(self.scene, "this", self.scene)
            return any(getattr(v.getSceneGraph(), "this", None) == me
                       for v in gdoc.mdiViewsOfType("Gui::View3DInventor"))
        except Exception as _fw_err:
            _fw_log("hlv.py:246", _fw_err)
            return False

    @staticmethod
    def _edge_set(root, lines, rgb, pattern, depth_function, width=1):
        from pivy import coin
        sep = coin.SoSeparator()
        depth = coin.SoDepthBuffer()
        depth.function = depth_function
        depth.write = False
        sep.addChild(depth)
        style = coin.SoDrawStyle()
        style.lineWidth = width
        style.linePattern = pattern
        sep.addChild(style)
        # an override material: the white faces' override can reach past the ObjectGroup (a plain group
        # in some scenes), and it beats an ordinary colour node, so the edges drew white on white
        colour = coin.SoMaterial()
        colour.diffuseColor.setValue(*rgb)
        colour.emissiveColor.setValue(*rgb)
        colour.setOverride(True)
        sep.addChild(colour)
        coords = coin.SoCoordinate3()
        pts = [(p.x, p.y, p.z) for line in lines for p in line]
        coords.point.setValues(0, len(pts), pts)
        sep.addChild(coords)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(lines), [len(line) for line in lines])
        sep.addChild(ls)
        root.addChild(sep)

    def draw(self):
        self.clear()
        gdoc = Gui.ActiveDocument
        if gdoc is not None:
            # another document's window in front: its own style (a new one opens as FreeCAD draws it;
            # HLR picked in one part no longer turned every other document HLR)
            want = self.modes.get(gdoc.Document.Name)
            if want != self.mode:
                self.mode, self.on = want, want == "hlv"
        if not self.mode or gdoc is None:
            return
        from pivy import coin
        view = gdoc.ActiveView
        if not hasattr(view, "getSceneGraph"):
            return          # a drawing sheet in front (TechDraw's page): no 3D scene to draw in
        scene = view.getSceneGraph()
        if self.mode == "swe":
            # Shaded With Edges, edges as Wireframe: every edge drawn, the ones behind the faces too
            root = coin.SoSeparator()
            root.setName("SWShadedEdgesWireframe")
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            root.addChild(pick)
            light2 = coin.SoLightModel()
            light2.model = coin.SoLightModel.BASE_COLOR
            root.addChild(light2)
            ghost = []
            lines = polylines(_shapes(gdoc.Document), DRAFT if draft_quality() else FINE, ghost)
            if lines:
                self._edge_set(root, lines, BLACK, 0xFFFF, coin.SoDepthBuffer.ALWAYS, edge_width())
            if ghost:
                self._edge_set(root, ghost, BLACK, PHANTOM, coin.SoDepthBuffer.ALWAYS, 1)
            scene.addChild(root)
            self.node, self.view, self.scene = root, view, scene
            self.doc_name = gdoc.Document.Name
            return
        # flat white faces: overrides ahead of FreeCAD's ObjectGroup, inside a separator that wraps the two,
        # so the white reaches the model only, and not the edges drawn after (an override blocks later
        # colours, even override ones), the dimensions, the highlight on top or a sketch being edited
        prefix = None
        if self.mode == "shd":
            # Shaded: the solids' own edge lines draw no pixels (each part's line style, not an override
            # on the whole model: sketches, curves and datums keep their lines) and stay pickable
            self._hush(gdoc.Document)
        else:
            prefix = _white_prefix(self.mode)
            wrap = None
            for i in range(scene.getNumChildren()):
                child = scene.getChild(i)
                if child.getName() == "ObjectGroup" and child.isOfType(coin.SoGroup.getClassTypeId()):
                    wrap = coin.SoSeparator()
                    wrap.setName("SWHiddenLinesWrap")
                    wrap.renderCaching = coin.SoSeparator.OFF
                    child.ref()                     # held while the wrapper stands in for it
                    wrap.addChild(prefix)
                    wrap.addChild(child)
                    wrap.addChild(_mask_callback(True))
                    scene.replaceChild(i, wrap)
                    break
            self.prefix_parent = wrap
            sec = _section()
            if sec is not None:
                # Section View draws the cut model itself (its caps): the same white faces and hushed
                # lines there, inside a separator in its root, so its sheet and handles keep their colours
                caps, sroot = sec.caps, sec.root
                k = sroot.findChild(caps)
                if k >= 0:
                    caps.ref()                      # held while the wrapper stands in for it
                    cwrap = coin.SoSeparator()
                    cwrap.setName("SWHiddenLinesSectionWrap")
                    cwrap.addChild(_white_prefix(self.mode))
                    cwrap.addChild(caps)
                    cwrap.addChild(_mask_callback(True))
                    sroot.replaceChild(k, cwrap)
                    self.sec_wrap = (sroot, cwrap, caps)
        # after the model: the edges, black where in front, grey dashed where behind (HLV)
        root = coin.SoSeparator()
        root.setName({"hlv": "SWHiddenLinesVisible", "shd": "SWShadedEdgeHighlight", "wf": "SWWireframe"}.get(self.mode, "SWHiddenLinesRemoved"))
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        light2 = coin.SoLightModel()
        light2.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light2)
        ghost = []
        sec = _section() if self.mode in ("hlr", "hlv", "wf") else None
        shapes = None
        if sec is not None:
            try:
                shapes = _section_shapes(gdoc.Document, sec)
            except Exception as _fw_err:
                _fw_log("hlv.py:section-shapes", _fw_err)
        lines = polylines(shapes if shapes is not None else _shapes(gdoc.Document), DRAFT if draft_quality() else FINE,
                          ghost if self.mode in ("hlr", "hlv") else None)
        self.keyed = keyed_polylines(gdoc.Document, DRAFT if draft_quality() else FINE)
        if lines and self.mode == "wf":
            self._edge_set(root, lines, _edge_rgb(), 0xFFFF, coin.SoDepthBuffer.ALWAYS, edge_width())
        elif lines and self.mode != "shd":     # Shaded: no edges drawn, only the highlight below
            self._edge_set(root, lines, _edge_rgb(), 0xFFFF, coin.SoDepthBuffer.LEQUAL, edge_width())
            if self.mode == "hlv":
                pattern = 0xFFFF if _option("HiddenEdges", "Dashed") == "Solid" else DASH
                self._edge_set(root, lines, _hidden_rgb(), pattern, coin.SoDepthBuffer.GREATER, edge_width())
            if ghost:
                self._edge_set(root, ghost, _edge_rgb(), PHANTOM, coin.SoDepthBuffer.LEQUAL, 1)
        self.hl = coin.SoSeparator()
        root.addChild(self.hl)
        at = scene.findChild(sec.root) if sec is not None else -1
        if at >= 0:
            scene.insertChild(root, at + 1)     # ahead of the section's clip plane, which clips everything after it
        else:
            scene.addChild(root)
        self.node, self.prefix, self.view, self.scene = root, prefix, view, scene
        self.doc_name = gdoc.Document.Name
        _watch_selection()
        self.highlight()

    def highlight(self):
        """FreeCAD's own edge lines draw nothing in HLR/HLV (see draw), its edge highlight with them:
        the picked edges are drawn here in the selection colour, the hovered one in the highlight
        colour, over the black ones."""
        hl = self.hl
        if hl is None or self.mode not in ("hlr", "hlv", "shd") or not self._alive():
            return
        from pivy import coin
        hl.removeAllChildren()
        picked, hovered = [], []
        try:
            for sel in Gui.Selection.getSelectionEx(self.doc_name, 0):
                for sub in sel.SubElementNames:
                    key = _edge_key(self.doc_name, sel.ObjectName, sub)
                    if key in self.keyed:
                        picked.append(self.keyed[key])
        except Exception as _fw_err:
            _fw_log("hlv.py:368", _fw_err)
        try:
            pre = Gui.Selection.getPreselection()
            if pre is not None and pre.DocumentName == self.doc_name:
                for sub in pre.SubElementNames:
                    key = _edge_key(self.doc_name, pre.ObjectName, sub)
                    if key in self.keyed:
                        hovered.append(self.keyed[key])
        except Exception as _fw_err:
            _fw_log("hlv.py:377", _fw_err)
        for lines, colour in ((picked, _colour("SelectionColor", 0x1CAD1C00)),
                              (hovered, _colour("HighlightColor", 0xE1E11400))):
            if lines:
                self._edge_set(hl, lines, colour, 0xFFFF, coin.SoDepthBuffer.LEQUAL, max(2, edge_width()))

    def _hook_theme(self):
        """A theme switch redraws the edges in the new theme's colour."""
        if getattr(self, "theme_hooked", False):
            return
        try:
            from . import style
            style.signals.theme_changed.connect(lambda *a: self.later())
            self.theme_hooked = True
        except Exception as _fw_err:
            _fw_log("hlv.py:theme", _fw_err)

    def _hook_styles(self):
        """Another display style (FreeCAD's own list or our buttons) turns Hidden Lines Visible off."""
        try:
            actions = Gui.Command.get("Std_DrawStyle").getAction()
        except Exception:
            actions = []
        for i, action in enumerate(actions):
            if action in self.hooked:
                continue
            action.triggered.connect(lambda *a, i=i: self._style_chosen(i))
            self.hooked.append(action)

    def _style_chosen(self, index):
        if getattr(self, "_setting", False):
            return
        if index == FLAT_LINES and _option("ShadedEdges", "HLR") == "Wireframe":
            self.set("swe")
            return
        if index == SHADED and App.GuiUp and _shaded_edge_pick():

            # picked: FreeCAD's Shaded leaves the edges out of the scene, so the view goes to Flat lines
            # with the edge lines drawing no pixels (pickable, unseen) and the highlight drawn here
            QtCore.QTimer.singleShot(0, self._to_shaded)
            return
        if index == WIREFRAME and App.GuiUp:
            # FreeCAD's Wireframe does not reach an assembly's components, and draws black lines that
            # vanish on a Dark viewport: every edge drawn here instead, in the theme's edge colour
            gdoc = Gui.ActiveDocument
            if gdoc is not None and (has_links(gdoc.Document) or _dark()):
                QtCore.QTimer.singleShot(0, lambda: self.set("wf"))
                return
        self.set(False)

    def _to_shaded(self):
        self._setting = True
        try:
            Gui.Command.get("Std_DrawStyle").getAction()[FLAT_LINES].trigger()
        except Exception as error:
            App.Console.PrintLog("FreeWorks: Shaded edges: %s\n" % error)
            return
        finally:
            self._setting = False
        self.set("shd")

    def _set_mode(self, mode):
        """Hidden Lines Removed or Visible: FreeCAD's No shading style plus the drawing."""
        self._setting = True
        try:
            Gui.Command.get("Std_DrawStyle").getAction()[NO_SHADING].trigger()
        except Exception as error:
            App.Console.PrintError("FreeCAD: Hidden Lines: %s\n" % error)
        finally:
            self._setting = False
        self.set(mode)


def edge_width():
    ""

    try:
        return max(1, App.ParamGet("User parameter:BaseApp/Preferences/View").GetInt("DefaultShapeLineWidth", 2))
    except Exception:
        return 2


HIDDEN = _HiddenEdges()


class _SelectionWatch:
    """Redraws the HLR/HLV edge highlight when the selection or the hover changes."""
    def _later(self, *args):
        if HIDDEN.mode in ("hlr", "hlv", "shd", "wf"):
            HIDDEN.hl_timer.start()

    addSelection = removeSelection = setSelection = clearSelection = _later
    setPreselection = removePreselection = _later


_selection_watch = None


def _watch_selection():
    global _selection_watch
    if _selection_watch is None:
        _selection_watch = _SelectionWatch()
        try:
            Gui.Selection.addObserver(_selection_watch)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Hidden Lines highlight: %s\n" % error)


class _Observer:
    def slotRecomputedDocument(self, doc):
        HIDDEN.later()

    def slotChangedObject(self, obj, prop):
        if prop == "Visibility":
            HIDDEN.later()

    def slotDeletedObject(self, obj):
        HIDDEN.later()

    def slotActivateDocument(self, doc):
        if HIDDEN.modes.get(doc.Name) and not HIDDEN.mode:
            HIDDEN.mode = HIDDEN.modes[doc.Name]     # later() redraws only with a style on
        HIDDEN.later()

    def slotDeletedDocument(self, doc):
        HIDDEN.modes.pop(doc.Name, None)        # a new document may get the closed one's name


def option_changed(key):
    """System Options > Display changed one of the edge options this drawing follows."""
    h = HIDDEN
    if key == "ShadedEdges":
        try:
            from . import viewsettings
            flat = viewsettings.draw_style_index() == FLAT_LINES and h.mode in (None, "swe")
        except Exception:
            flat = False
        if flat:
            h.set("swe" if _option("ShadedEdges", "HLR") == "Wireframe" else False)
            return
    h.later()


def _white_prefix(mode):
    """The overrides ahead of the model in HLR / HLV / Wireframe (see _HiddenEdges.draw)."""
    from pivy import coin
    prefix = coin.SoGroup()
    prefix.setName("SWHiddenLinesWhite")
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    light.setOverride(True)
    prefix.addChild(light)
    white = coin.SoMaterial()
    white.diffuseColor.setValue(*WHITE)
    white.emissiveColor.setValue(0, 0, 0)
    white.setOverride(True)
    prefix.addChild(white)
    # FreeCAD's own edge lines (white under the override) drew no colour but kept their depth, so
    # they hid stretches of the black edges drawn after: the near half of a hole's rim was gone in
    # HLR and dashed as hidden in HLV. A line pattern of 0 draws no pixels, so no depth either.
    hush = coin.SoDrawStyle()
    hush.linePattern = 0
    hush.setOverride(True)
    prefix.addChild(hush)
    if mode == "wf":
        # Wireframe: the model draws nothing at all (no colour, no depth); every edge is drawn after
        nodepth = coin.SoDepthBuffer()
        nodepth.write = False
        nodepth.setOverride(True)
        prefix.addChild(nodepth)

    prefix.addChild(_mask_callback(False))
    return prefix


def _section():
    """The live Section View on the active view when it draws the model cut itself (solid mode), else None."""
    try:
        from . import sectionview, sectionmore
        c = sectionview._controller
        sec = c.section if c is not None and c.active() else None
        if sec is None or not sectionmore.solid_mode(sec.settings):
            return None
        gdoc = Gui.ActiveDocument
        if gdoc is None or sec.view is not gdoc.ActiveView and \
                getattr(sec.view.getSceneGraph(), "this", 1) != getattr(gdoc.ActiveView.getSceneGraph(), "this", 2):
            return None
        return sec
    except Exception as _fw_err:
        _fw_log("hlv.py:section", _fw_err)
        return None


def _section_shapes(doc, sec):
    """The shapes as the Section View shows them: cut ones cut, the ones wholly cut away left out."""
    from . import sectionmore
    s = sec.settings
    frames = sectionmore.active_frames(s)
    region = sectionmore.removed_region(s, max(sec._size, 1.0), sec._center)
    out = []
    for name, shape, _colour in sectionmore.shown_with_names(doc, Gui.getDocument(doc.Name)):
        side = sectionmore._side(shape, region, frames) if sectionmore.body_cut(s, name) else "kept"
        if side == "removed":
            continue
        if side != "kept":
            shape = sectionmore.kept(shape, region)
        if shape is not None and not shape.isNull() and _has_edges(shape):
            out.append(shape)
    return out


def _shaded_edge_pick():
    ""
    return App.ParamGet(PARAMS).GetBool("ShadedEdgePick", True)


def shaded():
    ""
    return HIDDEN.mode == "shd"


def active():
    """Hidden Lines Visible is on."""
    return HIDDEN.on


def mode():
    """None, "hlr", "hlv", "swe" or "shd" (this module's Wireframe reads as FreeCAD's: None)."""
    return None if HIDDEN.mode == "wf" else HIDDEN.mode


def hlr_active():
    return HIDDEN.mode == "hlr"


def draft_quality():
    return App.ParamGet(PARAMS).GetBool(DRAFT_KEY, False)


def set_draft_quality(on):
    App.ParamGet(PARAMS).SetBool(DRAFT_KEY, bool(on))
    if HIDDEN.on:
        HIDDEN.draw()


def _on_drawing(name):
    """On a drawing, the style goes to the picked views (drawselect, drawings-land23): True when done."""
    try:
        from . import drawings
        if not drawings.in_drawing():
            return False
        from . import drawselect
        drawselect.display_style(name)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hidden Lines on a drawing: %s\n" % error)
        return False


def show():
    """Hidden Lines Visible on the active view (or the picked drawing views)."""
    if _on_drawing("Hidden Lines Visible"):
        return
    HIDDEN._set_mode("hlv")


def show_hlr():
    """Hidden Lines Removed on the active view (or the picked drawing views)."""
    if _on_drawing("Hidden Lines Removed"):
        return
    HIDDEN._set_mode("hlr")


class _HLRCommand:
    def GetResources(self):
        return {"MenuText": "Hidden Lines Removed", "Pixmap": "DrawStyleHiddenLine",
                "ToolTip": "White faces and black edges, with the hidden edges left out."}

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        show_hlr()


class _Command:
    def GetResources(self):
        return {"MenuText": "Hidden Lines Visible", "Pixmap": "DrawStyleHiddenLine",
                "ToolTip": "Edges only: visible edges solid, hidden edges grey and dashed."}

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        show()


class _DraftQuality:
    def GetResources(self):
        return {"MenuText": "Draft Quality HLR/HLV", "Pixmap": "DrawStyleHiddenLine",
                "ToolTip": "Hidden Lines Visible draws its hidden edges from coarser curves: quicker, rougher",
                "Checkable": draft_quality(), "CmdType": "ForEdit"}      # extapps77

    def Activated(self, checked=None):
        set_draft_quality(not draft_quality() if checked is None else bool(checked))

    def IsActive(self):
        state = draft_quality()
        try:
            actions = Gui.Command.get("SWStyle_DraftQualityHLR").getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != state:
                blocked = action.blockSignals(True)
                action.setChecked(state)
                action.blockSignals(blocked)
        return Gui.ActiveDocument is not None


_observer = None


def register():
    global _observer
    if "SWStyle_HiddenLinesVisible" not in Gui.listCommands():
        Gui.addCommand("SWStyle_HiddenLinesVisible", _Command())
    if "SWStyle_HiddenLinesRemoved" not in Gui.listCommands():
        Gui.addCommand("SWStyle_HiddenLinesRemoved", _HLRCommand())
    if "SWStyle_DraftQualityHLR" not in Gui.listCommands():
        Gui.addCommand("SWStyle_DraftQualityHLR", _DraftQuality())
    try:
        from . import checkstate      # the Display Style flyout and buttons tick the style in use
        checkstate.register("SWStyle_HiddenLinesVisible", lambda: HIDDEN.mode == "hlv")
        checkstate.register("SWStyle_HiddenLinesRemoved", lambda: HIDDEN.mode == "hlr")
    except Exception as _fw_err:
        _fw_log("hlv.py:571", _fw_err)
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        # Shaded With Edges follows the Display option from the first time it is picked
        QtCore.QTimer.singleShot(0, HIDDEN._hook_styles)
