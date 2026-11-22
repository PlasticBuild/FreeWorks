"""A failure in a command that the user should hear about: one line on the status bar, in the add-on's own words,
for 8 seconds, and the error itself in the Log (Report view at Log level).
Never raises, so the command that calls it ends exactly as it did before."""
import FreeCAD as App


def tell(text, err=None, ms=8000):
    try:
        App.Console.PrintLog("%s %s\n" % (text, "(%s)" % err if err is not None else ""))
    except Exception:
        return
    if not App.GuiUp:
        return
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        return
