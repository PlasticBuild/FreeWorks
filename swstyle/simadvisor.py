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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

TITLE = "Simulation Advisor"
INDEX = 90                     # its Task Pane page (no tab of its own on the rail)


CONCERNS = (("I am concerned about excessive deformation or stresses.", "static"),
            ("I am concerned about the effect of load/unload cycles.", "fatigue"),
            ("I am concerned about sudden collapse under compression.", "buckling"),
            ("I am concerned about excessive shaking.", "frequency"),
            ("I am concerned about temperatures.", "thermomech"))

STEPS = ("Study", "Bodies and Material", "Interactions", "Mesh and Run", "Results")
STEP_OF = {"study": 0, "material": 1, "run": 3, "results": 4}
SKIP_WELCOME = "SimAdvisorSkipWelcome"
TYPE_TEXT = {"static": "Stresses, displacements and the factor of safety under loads that do not change.",
             "frequency": "The natural frequencies and their mode shapes.",
             "buckling": "The load factor at which a slender part buckles, and its shape.",
             "thermomech": "Temperatures and heat flow, steady state or over time.",
             "fatigue": "Damage and life after many load cycles, from static studies.",
             "drop": "Stresses in the part just after it hits the floor.",
             "nonlinear": "Large displacements and yielding, in time steps.",
             "check": "The setup, written and checked without a solve."}

# page key -> (title, what it is for, words in the type names of the study objects it lists, tool keys)
FIX_WORDS = ("Fixed", "Displacement", "PlaneRotation", "Spring", "RigidBody")
LOAD_WORDS = ("Force", "Pressure", "SelfWeight", "Centrif", "Bearing", "Temperature")
THERMAL_WORDS = ("Temperature", "Heatflux", "BodyHeatSource", "InitialTemperature")
CONNECT_WORDS = ("Contact", "Tie")
PAGES = {
    "study": ("Study", "The study is set up for the question you asked. Its options are in Study Properties.",
              (), ("SIM_Props", "SIM_NewStudy", "SIM_Duplicate")),
    "material": ("Bodies and Material", "Give each body its material: the stresses and displacements are only as good "
                 "as its stiffness, and the factor of safety as its strength.", ("MaterialSolid", "MaterialCommon"),
                 ("SIM_ApplyMaterial",)),
    "fixtures": ("Fixtures Advisor", "Hold the part where it is held in use: fixed faces, rollers, hinges or an elastic "
                 "support. Without fixtures a static study cannot solve.", FIX_WORDS,
                 ("SIM_Fixed", "SIM_Roller", "SIM_Hinge", "SIM_Elastic", "SIM_Rigid")),
    "loads": ("External Loads Advisor", "Put on the loads the part carries: forces, pressures, its weight, spinning or a "
              "bearing load.", LOAD_WORDS,
              ("SIM_Force", "SIM_Torque", "SIM_Pressure", "SIM_Gravity", "SIM_Centrifugal", "SIM_Bearing", "SIM_RemoteLoad",
               "SIM_DistributedMass", "SIM_Temperature")),
    "thermal": ("Thermal Loads", "Give the heat that goes in and out: temperatures, convection, heat flux, heat power "
                "or radiation, and the temperature the part starts from.", THERMAL_WORDS,
                ("SIM_Temperature", "SIM_Convection", "SIM_HeatFlux", "SIM_BodyHeat", "SIM_Radiation", "SIM_InitialTemp")),
    "drop": ("Drop Test Setup", "Give the drop height (or the velocity at impact) and gravity, then what to keep of "
             "the impact.", (), ("#drop_setup", "#result_options")),
    "events": ("Loading Events", "Add the events: how many cycles of which static study, and how the load "
               "repeats. Then check the S-N curve of the material.", ("FatigueEvent",),
               ("#add_event", "#fatigue_data")),
    "pvsetup": ("Pressure Vessel Setup", "Pick the static studies to combine (one load case each, on one mesh) and "
                "their factors: a linear combination, or the square root of the sum of their squares.", (),
                ("#pv_setup",)),
    "goals": ("Goals and Constraints", "Say what the optimisation aims at and how much mass to take away, and which "
              "regions must keep their material.", (), ("#topology_goals",)),
    "connections": ("Connections Advisor", "Where faces touch, say how they meet: bonded, or in contact so that they "
                    "can slide apart. A single body needs none.", CONNECT_WORDS,
                    ("SIM_Contact", "SIM_Bonded", "SIM_Interaction", "SIM_SpringConnector", "SIM_Pin", "SIM_Bolt",
                     "SIM_BearingConnector", "SIM_RigidConnector")),
    "run": ("Mesh and Run", "Mesh the part (a finer mesh where the stress changes fast) and run the study.",
            (), ("SIM_Mesh", "SIM_MeshControl", "SIM_Run", "SIM_RunAll")),
    "results": ("Results Advisor", "Look at the results: double-click a plot to show it, add plots, probe values "
                "and make the report.", (), ("SIM_Results", "SIM_Plot", "SIM_Deform", "SIM_Probe", "SIM_Compare",
                                              "SIM_Report")),
}
ORDER = {
    "static": ("study", "material", "fixtures", "loads", "connections", "run", "results"),
    "thermomech": ("study", "material", "thermal", "connections", "run", "results"),
    "drop": ("study", "material", "drop", "connections", "run", "results"),
    "fatigue": ("study", "events", "run", "results"),
    "topology": ("study", "material", "fixtures", "loads", "goals", "run", "results"),
    "pressure": ("study", "pvsetup", "run", "results"),
}
OPTIONAL = {("frequency", "fixtures"), ("frequency", "loads"), ("thermomech", "connections"),
            ("drop", "connections")}
for _k in ("static", "frequency", "buckling", "nonlinear", "lineardynamic", "check"):
    ORDER.setdefault(_k, ORDER["static"])
    OPTIONAL.add((_k, "connections"))
# the Advisor entries on the Simulation tab: key -> (label, page)

# those of the flyout's first tool)
ENTRIES = (("SIM_StudyAdvisor", "Simulation Advisor", "study", "SIM_Advisor", None),
           ("SIM_FixAdvisor", "Fixtures Advisor", "fixtures", "SIM_Fixed", "Fixtures\nAdvisor"),
           ("SIM_LoadAdvisor", "External Loads Advisor", "loads", "SIM_Force", "External Loads\nAdvisor"),
           ("SIM_ConnAdvisor", "Connections Advisor", "connections", "SIM_Contact", "Connections\nAdvisor"),
           ("SIM_ResAdvisor", "Results Advisor", "results", "SIM_Results", "Results\nAdvisor"))
STATE = {"page": None}


# --------------------------------------------------------------------------- the study
def study(doc=None):
    try:
        from . import simtree
        a = simtree._ctx_study()
        if a is not None:
            return a
    except Exception as _fw_err:
        _fw_log("simadvisor.py:study", _fw_err)
    try:
        from . import addintabs
        doc = doc or App.ActiveDocument
        return addintabs._active_analysis(doc) if doc is not None else None
    except Exception:
        return None


def kind_of(a):
    if a is None:
        return None
    try:
        from . import simtypes
        return simtypes.study_type(a)
    except Exception:
        return "static"


def pages_of(a):
    k = kind_of(a)
    return ORDER.get(k, ORDER["static"]) if k else ("study",)


def _kinds(o):
    return "%s %s" % (getattr(o, "TypeId", ""), getattr(getattr(o, "Proxy", None), "Type", ""))


def items(a, page):
    """The study objects a page lists: [(label, object)] (Results: the plots, [(title, plot name)])."""
    if a is None:
        return []
    if page == "results":
        try:
            from . import simplots
            return [(simplots.title(p), p["name"]) for p in simplots.plots(a)]
        except Exception:
            return []
    if page == "pvsetup":
        try:
            from . import simpressure
            return [("%s (factor %g)" % (st.Label, f), st) for st, f in simpressure.studies(a)]
        except Exception:
            return []
    if page == "events":
        try:
            from . import simtypes
            return [(e.Label, e) for e in simtypes.events(a)]
        except Exception:
            return []
    words = PAGES[page][2]
    out = []
    for o in a.Group:
        k = _kinds(o)
        if not any(w in k for w in words) or "Result" in k or "Nonlinear" in k:
            continue
        if page == "loads" and "InitialTemperature" in k:
            continue
        out.append((o.Label, o))
    return out


def done(a, page):
    """(done, text) of one page from what the study holds."""
    if a is None:
        return False, "no study yet"
    k = kind_of(a)
    if page == "study":
        return True, TYPE_NAMES().get(k, k)
    if page == "material":
        try:
            from . import simtree
            mats = simtree._materials(a)
        except Exception:
            mats = [o for o in a.Group if "Material" in _kinds(o)]
        return bool(mats), (mats[0].Label if len(mats) == 1 else "%d materials" % len(mats)) if mats else "no material yet"
    if page == "run":
        try:
            from . import simplots
            if simplots.result(a) is not None:
                return True, "run"
        except Exception as _fw_err:
            _fw_log("simadvisor.py:run", _fw_err)
        if any(o.isDerivedFrom("Fem::FemResultObject") for o in a.Group):
            return True, "run"
        return False, "not run"
    if page == "results":
        ran = done(a, "run")[0]
        n = len(items(a, "results"))
        return ran and n > 0, ("%d plot%s" % (n, "" if n == 1 else "s")) if ran else "run the study first"
    if page == "pvsetup":
        try:
            from . import simpressure
            n = len(simpressure.studies(a))
            return n > 0, ("%s of %d stud%s" % (simpressure.method_word(a), n, "y" if n == 1 else "ies")) if n else "to do"
        except Exception:
            return False, "to do"
    if page == "goals":
        try:
            from . import simtopology
            v = simtopology.values(a)
            return True, "reduce mass by %g %%" % float(v["reduce"])
        except Exception:
            return True, "defaults"
    if page == "drop":
        try:
            from . import simtypes
            v = simtypes.drop_values(a)
            if v.get("type") == "Velocity at impact":
                return True, "%g mm/s at impact" % float(v["velocity"])
            return True, "from %g %s" % (float(v["height"]), v.get("height_unit", "mm"))
        except Exception:
            return True, "defaults"
    found = items(a, page)
    if found:
        return True, "%d added" % len(found) if len(found) > 1 else found[0][0]
    return False, "optional" if (k, page) in OPTIONAL else "to do"


def TYPE_NAMES():
    try:
        from . import simtypes
        return {key: name for _g, name, key, _cmd in simtypes.TYPES}
    except Exception:
        return {"static": "Static"}


def next_page(a):
    for p in pages_of(a):
        ok, _t = done(a, p)
        if not ok and (kind_of(a), p) not in OPTIONAL:
            return p
    return None


# --------------------------------------------------------------------------- tools
def tools(a, page):
    """The tools a page offers: [(label, key)] ('#name' keys run a function of the study); only those that fit."""
    out = []
    try:
        from . import catalog, simfit
    except Exception:
        return out
    for key in PAGES[page][3]:
        if key.startswith("#"):
            label = SPECIAL[key][0]
            if a is not None:
                out.append((label, key))
            continue
        c = catalog.BY_KEY.get(key)
        if c is None or not simfit.fits(key, a):
            continue
        if a is None and key not in ("SIM_NewStudy",):
            continue
        out.append((c.label, key))
    return out


# the study's own PMs that have no Simulation tab key: key -> (label, simtypes function of the study)
SPECIAL = {"#drop_setup": ("Drop Test Setup", "open_drop_setup"), "#result_options": ("Result Options", "open_result_options"),
           "#add_event": ("Add Event", "open_event"), "#fatigue_data": ("Fatigue Data (S-N curve)", "open_fatigue_data"),
           "#topology_goals": ("Goals and Constraints", "simtopology.open_goals"),
           "#pv_setup": ("Pressure Vessel Setup", "simpressure.open_setup")}


def run_tool(a, key):
    if key in SPECIAL:
        from . import simtypes
        if Gui.Control.activeDialog():
            _say("%s: finish the open page first (OK or Cancel)" % SPECIAL[key][0])
            return None
        where, _dot, fn = SPECIAL[key][1].rpartition(".")
        if where:                                  # another module's PM (simtopology)
            import importlib
            return getattr(importlib.import_module("." + where, __package__), fn)(a)
        return getattr(simtypes, fn)(a)
    from . import shell
    sh = shell.shell()
    b = sh.binding(key)
    b.resolve()
    b.update_state()
    if not b.enabled:
        _say("%s: finish the open page first (OK or Cancel)" % b.cmd.label)
        return None
    return b.run()


def edit_item(a, page, item):
    if page == "results":
        from . import simplots
        return simplots.show(a, item)
    if page == "pvsetup":
        from . import simpressure
        return simpressure.open_setup(a)
    from . import simtree
    return simtree.edit(item)


def _say(text, ms=8000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception as _fw_err:
        _fw_log("simadvisor.py:say", _fw_err)


# --------------------------------------------------------------------------- the page
if Gui is not None:
    LINK = "text-align: left; color: palette(link); text-decoration: underline; border: none; padding: 2px 0px;"

    _ARROW = []

    def _arrow():
        ""
        if not _ARROW:
            from PySide import QtGui
            pm = QtGui.QPixmap(12, 12)
            pm.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setBrush(QtGui.QColor("#2e9b3a"))
            p.setPen(QtGui.QColor("#1d6b26"))
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2, 1), QtCore.QPointF(11, 6), QtCore.QPointF(2, 11)]))
            p.end()
            _ARROW.append(QtGui.QIcon(pm))
        return _ARROW[0]

    def _skip_welcome():
        try:
            return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool(SKIP_WELCOME, False)
        except Exception:
            return False

    def _set_skip_welcome(on):
        try:
            App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").SetBool(SKIP_WELCOME, bool(on))
        except Exception as _fw_err:
            _fw_log("simadvisor.py:skip", _fw_err)


    INTRO = {
        "welcome": ("Welcome to the Simulation Advisor",
                    "The Simulation Advisor helps you pick the study for your question, then walks you through its "
                    "steps: the bodies and their material, how the part is held and loaded, the mesh and the run, and "
                    "the results.<br><br>Every tool it offers is also on the Simulation tab, in the study tree's "
                    "right-click menus and in the menus."),
        "concern": ("To help you create the proper study, select one of the following:", ""),
        "deform": ("Deformation", "A displacement plot shows best how much the part deforms. Tell us more about your "
                   "concern."),
        "strength": ("Strength", "Stress shows best where the part may fail. A ductile material (most metals) fails "
                     "when its von Mises stress passes its yield strength; a brittle one (cast iron, glass, many "
                     "plastics) when its largest principal stress passes its tensile strength. Give the material those "
                     "strengths so the factor of safety is right."),
    }
    DEFORM = ("Nothing in my design may deform more than a specified amount.",
              "I need to limit deformation in specified regions of my model (parts, faces, edges, vertices).")
    STRENGTH = ("I don't know where to expect failure. Check the whole model.",
                "I am most concerned about failure at specific locations in my model.")

    class Page(QtWidgets.QWidget):
        def __init__(self, pane=None):
            super().__init__(pane)
            self.setObjectName("SWSimulationAdvisor")
            self.a = None
            self.page = "study"
            self.intro = "concern" if _skip_welcome() else "welcome"
            self.make = "static"
            lay = QtWidgets.QVBoxLayout(self)

            self.stepbox = QtWidgets.QFrame(self)
            self.stepbox.setObjectName("SWSimulationAdvisorSteps")
            self.stepbox.setFrameShape(QtWidgets.QFrame.StyledPanel)
            sl = QtWidgets.QVBoxLayout(self.stepbox)
            sl.setContentsMargins(6, 4, 6, 4)
            sl.setSpacing(0)
            self.step_buttons = []
            for i, name in enumerate(STEPS):
                b = QtWidgets.QPushButton("%d  %s" % (i + 1, name), self.stepbox)
                b.setObjectName("SWSimulationAdvisorStep")
                b.setFlat(True)
                b.clicked.connect(lambda _c=False, i=i: self.go_step(i))
                sl.addWidget(b)
                self.step_buttons.append(b)
            lay.addWidget(self.stepbox)
            self.head = QtWidgets.QLabel(self)
            self.head.setObjectName("SWSimulationAdvisorTitle")
            self.head.setWordWrap(True)
            lay.addWidget(self.head)
            self.text = QtWidgets.QLabel(self)
            self.text.setWordWrap(True)
            lay.addWidget(self.text)
            self.links_box = QtWidgets.QWidget(self)               # the green-arrow links of the intro pages
            self.links_lay = QtWidgets.QVBoxLayout(self.links_box)
            self.links_lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.links_box)
            self.links = []
            self.no_welcome = QtWidgets.QCheckBox("Do not show me this again", self)
            self.no_welcome.setObjectName("SWSimulationAdvisorNoWelcome")
            self.no_welcome.setChecked(_skip_welcome())
            self.no_welcome.toggled.connect(_set_skip_welcome)
            lay.addWidget(self.no_welcome)
            self.have_label = QtWidgets.QLabel("In this study:", self)
            lay.addWidget(self.have_label)
            self.have = QtWidgets.QListWidget(self)
            self.have.setObjectName("SWSimulationAdvisorItems")
            self.have.itemDoubleClicked.connect(self._edit)
            lay.addWidget(self.have, 3)
            self.tools_box = QtWidgets.QWidget(self)
            self.tools_lay = QtWidgets.QVBoxLayout(self.tools_box)
            self.tools_lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.tools_box)
            lay.addStretch(1)                                     # a page without a list keeps its text together
            nav = QtWidgets.QHBoxLayout()
            self.back = QtWidgets.QPushButton("Back", self)
            self.back.setObjectName("SWSimulationAdvisorBack")
            self.back.setStyleSheet(LINK)
            self.back.clicked.connect(self._back)
            self.next = QtWidgets.QPushButton("Next", self)
            self.next.setObjectName("SWSimulationAdvisorNext")
            self.next.setStyleSheet(LINK)
            self.next.clicked.connect(self._next)
            nav.addWidget(self.back)
            nav.addStretch(1)
            nav.addWidget(self.next)
            lay.addLayout(nav)
            self.buttons = []
            self.shown = None
            self.timer = QtCore.QTimer(self)
            self.timer.setInterval(1000)
            self.timer.timeout.connect(self._tick)
            self.timer.start()

        # ---- navigation
        def go(self, page):
            self.page = page
            STATE["page"] = page
            self.refresh(force=True)

        def go_step(self, i):
            order = list(pages_of(self.a))
            first = next((p for p in order if STEP_OF.get(p, 2) == i), None)
            if first is None:                      # a step this study type has no page for: the nearest before it
                first = next((p for p in reversed(order) if STEP_OF.get(p, 2) <= i), order[0])
            if self.a is None:
                self.intro = "concern" if _skip_welcome() else "welcome"
            self.go(first)

        def step(self, d):
            order = list(pages_of(self.a))
            i = order.index(self.page) if self.page in order else 0
            i = max(0, min(len(order) - 1, i + d))
            self.go(order[i])

        def _intro_go(self, state, make=None):
            self.intro = state
            if make:
                self.make = make
            self.refresh(force=True)

        def _back(self):
            if self.a is None and self.page == "study":
                prev = {"concern": "welcome", "deform": "concern", "strength": "deform", "summary": "concern"}
                to = prev.get(self.intro, "welcome")
                if self.intro == "summary" and self.make == "static":
                    to = "strength"
                return self._intro_go(to)
            self.step(-1)

        def _next(self):
            if self.a is None and self.page == "study":
                nxt = {"welcome": "concern", "deform": "strength", "strength": "summary"}
                return self._intro_go(nxt.get(self.intro, self.intro))
            self.step(1)

        def _tick(self):
            if self.isVisible():
                self.refresh()

        def state(self):
            a = self.a
            order = pages_of(a)
            return (getattr(a, "Name", None), kind_of(a), self.page, self.intro, self.make,
                    tuple(done(a, p) for p in order), tuple(t for t, _o in items(a, self.page)) if a else (),
                    tuple(tools(a, self.page)))

        def _clear(self, widgets):
            for b in widgets:
                b.setParent(None)
                b.deleteLater()
            del widgets[:]

        def _link(self, text, fn, parent_lay, store, name="SWSimulationAdvisorLink"):
            b = QtWidgets.QPushButton(_arrow(), text, self)
            b.setObjectName(name)
            b.setFlat(True)
            b.setStyleSheet(LINK)
            b.clicked.connect(fn)
            parent_lay.addWidget(b)
            store.append(b)
            return b

        def refresh(self, force=False):
            a = study()
            try:
                a is not None and a.Label
            except Exception:
                a = None
            if a is not self.a:
                self.a = a
                force = True
            order = pages_of(a)
            if self.page not in order:
                self.page = "study"
            s = self.state()
            if not force and s == self.shown:
                return
            self.shown = s
            nxt = next_page(a)
            cur = STEP_OF.get(self.page, 2)
            for i, b in enumerate(self.step_buttons):
                pages = [p for p in order if STEP_OF.get(p, 2) == i]
                ok = a is not None and bool(pages) and all(done(a, p)[0] or (kind_of(a), p) in OPTIONAL for p in pages)
                b.setText("%d  %s%s" % (i + 1, STEPS[i], "   ✔" if ok else ""))
                f = b.font()
                f.setBold(i == cur)
                b.setFont(f)
                later = a is None and i > 0
                b.setStyleSheet("text-align: left; border: none; padding: 1px 0px;%s" % (" color: palette(mid);" if later else ""))
                b.setVisible(bool(pages) or a is None)
            self._clear(self.links)
            intro = a is None and self.page == "study"
            self.no_welcome.setVisible(intro and self.intro == "welcome")
            if intro:
                self._intro()
            else:
                title, what, _w, _k = PAGES[self.page]
                if a is None:
                    self.head.setText("<b>%s</b>" % title)
                else:
                    self.head.setText("<b>%s</b> &nbsp; %s (%s)%s" % (
                        title, a.Label, TYPE_NAMES().get(kind_of(a), kind_of(a)),
                        ("<br>Next: %s" % PAGES[nxt][0]) if nxt else "<br>All steps done: look at the results"))
                self.text.setText(what)
            self.have.clear()
            listed = items(a, self.page) if not intro else []
            for text, obj in listed:
                it = QtWidgets.QListWidgetItem(text)
                it.setData(QtCore.Qt.UserRole, obj if isinstance(obj, str) else obj.Name)
                self.have.addItem(it)
            showing = a is not None and self.page not in ("run", "study") and (bool(listed) or bool(PAGES[self.page][2])
                                                                               or self.page == "results")
            self.have_label.setVisible(showing)
            self.have.setVisible(showing)
            self.have_label.setText("Plots (double-click to show):" if self.page == "results" else
                                    "In this study (double-click to edit):")
            self._clear(self.buttons)
            if not intro:
                for label, key in tools(a, self.page):
                    b = QtWidgets.QPushButton(_arrow(), label, self.tools_box)
                    b.setObjectName("SWSimulationAdvisorTool")
                    b.setProperty("key", key)
                    b.setFlat(True)
                    b.setStyleSheet(LINK)
                    b.clicked.connect(lambda _c=False, k=key: self._tool(k))
                    self.tools_lay.addWidget(b)
                    self.buttons.append(b)
            if intro:
                self.back.setVisible(self.intro != "welcome")
                self.next.setVisible(self.intro in ("welcome", "deform", "strength"))
            else:
                i = list(order).index(self.page)
                self.back.setVisible(i > 0)
                self.next.setVisible(i < len(order) - 1)

        def _intro(self):
            st = self.intro
            if st == "summary":
                name = TYPE_NAMES().get(self.make, self.make)
                self.head.setText("The following study will be created:")
                self.text.setText("• %s Study<br><br><small>The Advisor is a guide for designers. Before a part "
                                  "is released, have its study checked by someone who does analysis, and test the "
                                  "part.</small>" % name)
                self._link("Create a %s Study." % name, self.start_study, self.links_lay, self.links,
                           "SWSimulationAdvisorCreate")
                return
            title, text = INTRO[st]
            self.head.setText("<b>%s</b>" % title)
            self.text.setText(text)
            if st == "concern":
                for label, kind in CONCERNS:
                    nxt = "deform" if kind == "static" else "summary"
                    self._link(label, lambda _c=False, n=nxt, k=kind: self._intro_go(n, k), self.links_lay, self.links)
            elif st == "deform":
                for label in DEFORM:
                    self._link(label, lambda _c=False: self._intro_go("strength", "static"), self.links_lay, self.links)
            elif st == "strength":
                for label in STRENGTH:
                    self._link(label, lambda _c=False: self._intro_go("summary", "static"), self.links_lay, self.links)

        def goal_kind(self):
            return self.make

        def _tool(self, key):
            try:
                run_tool(self.a, key)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD Simulation Advisor: %s\n" % error)
                _say("%s: %s" % (TITLE, error))
            self.refresh(force=True)

        def _edit(self, it):
            a = self.a
            if a is None:
                return
            ref = it.data(QtCore.Qt.UserRole)
            try:
                if self.page == "results":
                    edit_item(a, "results", ref)
                else:
                    o = a.Document.getObject(ref)
                    if o is not None:
                        edit_item(a, self.page, o)
            except Exception as error:
                _say("%s: %s" % (TITLE, error))

        def start_study(self):
            from . import addintabs, simtypes
            addintabs.load("FEM")
            doc = App.ActiveDocument
            obj = addintabs._main_solid(doc) if doc else None
            if obj is None:
                _say("%s: the document has no solid body to study" % TITLE)
                addintabs._warn(TITLE, "The document has no solid body to study.")
                return None
            doc.openTransaction("Study Advisor")
            try:
                a = simtypes.new_typed_study(doc, self.goal_kind(), None)
            except Exception as error:
                doc.abortTransaction()
                addintabs._warn(TITLE, str(error))
                return None
            doc.commitTransaction()
            addintabs._set_active(a)
            try:
                from . import simtree
                simtree.activate(doc, a)
            except Exception as _fw_err:
                _fw_log("simadvisor.py:activate", _fw_err)
            try:
                addintabs._refresh_buttons()
            except Exception as _fw_err:
                _fw_log("simadvisor.py:buttons", _fw_err)
            self.a = a
            self.go("study")
            return a


def _tabs():
    try:
        from . import chrome
        from .widgets import alive
        return [t for t in Gui.getMainWindow().findChildren(chrome.TaskPaneTabs) if alive(t)]
    except Exception:
        return []


def open_page(page=None):
    """Opens the Simulation Advisor in the Task Pane at a page (the first one still to do by default)."""
    from . import taskpane
    taskpane.register_page(INDEX, lambda pane: Page(pane))
    tabs = _tabs()
    if not tabs:
        return None
    pane = taskpane.pane_of(tabs[0])
    w = pane.page(INDEX)
    a = study()
    w.a = a
    w.page = page or next_page(a) or "study"
    if w.page not in pages_of(a):
        w.page = "study" if page in (None, "study") or a is None else pages_of(a)[0]
    STATE["page"] = w.page
    pane.show_tab(INDEX)
    pane.title.setText(TITLE)
    w.refresh(force=True)
    return w


# --------------------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, label, tip, page):
        self.label, self.tip, self.page = label, tip, page

    def GetResources(self):
        icon = ""
        try:
            from . import simicons
            icon = simicons.svg("SIM_Advisor") or ""
        except Exception as _fw_err:
            _fw_log("simadvisor.py:icon", _fw_err)
        return {"MenuText": self.label, "ToolTip": self.tip, "Pixmap": icon}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        if self.page == "results":
            a = study()
            if a is not None and not done(a, "run")[0]:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Results Advisor",
                                              "There are no results to show yet: run the study first.")
                return
        try:
            if open_page(self.page) is None:
                _old(self.page)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD Simulation Advisor: %s\n" % error)
            _old(self.page)


def _old(page):
    """No Task Pane (another shell): the Study Advisor window of simstudy."""
    from . import simstudy
    a = study()
    if a is None:
        return simstudy._advisor0() if hasattr(simstudy, "_advisor0") else None
    return simstudy.open_advisor0(a) if hasattr(simstudy, "open_advisor0") else None


TIPS = {"study": "Helps you pick the study for your question and walks you through its steps, in the Task Pane.",
        "fixtures": "The Simulation Advisor's Fixtures page: what holds the part, and the fixture tools.",
        "loads": "The Simulation Advisor's External Loads page: the loads on the part, and the load tools.",
        "connections": "The Simulation Advisor's Connections page: contact and bonding between faces.",
        "results": "The Simulation Advisor's Results page: the plots, probes and the report."}


def install():
    """The Advisor commands and keys; Study Advisor (and a new study) opens the Task Pane page."""
    if Gui is None:
        return
    from . import catalog, simstudy
    have = set(Gui.listCommands())
    for key, label, page, picture, caption in ENTRIES:
        name = "SWStyle_SimAdvisor_" + page
        if name not in have:
            Gui.addCommand(name, _Cmd(label, TIPS[page], page))
        icon = None
        try:
            from . import simicons
            icon = simicons.family_or_drawing(picture)
        except Exception as _fw_err:
            _fw_log("simadvisor.py:keyicon", _fw_err)
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (name,), icon, TIPS[page], caption=caption)
    old = catalog.BY_KEY.get("SIM_Advisor")
    if old is not None and "SWStyle_SimAdvisor_study" not in old.natives:
        old.natives = ("SWStyle_SimAdvisor_study",) + tuple(old.natives)
    if not getattr(simstudy, "_fw_pane_advisor", False):
        simstudy._advisor0 = simstudy._advisor
        simstudy.open_advisor0 = simstudy.open_advisor

        def open_advisor(analysis):
            try:
                w = open_page()
                if w is not None:
                    return w
            except Exception as error:
                App.Console.PrintLog("FreeCAD Simulation Advisor: %s\n" % error)
            return simstudy.open_advisor0(analysis)
        simstudy.open_advisor = open_advisor
        simstudy._fw_pane_advisor = True
