# Your first 15 minutes (public alpha)

Sketching is the part we most want you to push on: **snapping** (where the pointer lands) and **relations** (what the sketch adds for you). Install first (`QUICKSTART-ALPHA.md`, section 1), then work through this page. Each line says what you should see. If it does not match, that is exactly what we want to hear about.

## Minutes 0 to 3: get a sketch open
1. Ctrl+N, Part, OK. Click **Front Plane** in the tree, then **Sketch**. The view turns to face the plane.
2. Pick the **Line** tool on the Sketch tab.

## Minutes 3 to 8: snapping (keep Line or Corner Rectangle running)
1. **Start at the origin:** move the pointer over the red origin arrows. It snaps there, and a small yellow square beside the pointer shows **Coincident**. Click.
2. **Level and plumb:** move right, nearly level. A pale dotted line appears and the square shows **Horizontal**. Click. Move straight up: **Vertical**. A line that is only close to level but not within a pixel or so should *not* take the relation.
3. **Midpoint:** hover over the middle of your first line, wait a moment, then start a new line there. The square shows **Midpoint**.
4. **Wake a point:** hover over an end point for a second, then move a new line's end level with it. The new end snaps exactly level with it. No relation is added just for lining up (the square stays white). Tell us if it lands a little off.
5. **Circles:** draw a circle, then start a Line and move the pointer round it. You land on its centre and on its top, bottom, left and right points; at a top or bottom point the tiles show On Edge and Vertical.
6. **Edges of a solid:** extrude any sketch (Features, Extruded Boss/Base), start a new sketch on a face and draw near an edge. The pointer snaps to the model's edges and vertices too.
7. **Keys:** hold **Ctrl** while you click: no snap, no relation. Press **F3**: the status bar says snapping is off; press again to turn it back on. **Shift** snaps the length to the grid step once the direction is set.

## Minutes 8 to 12: relations
1. **See them:** finish an entity. Small green markers show its relations. Pick it: the property panel lists them; pick a relation there to highlight what it joins.
2. **Add one by hand:** Ctrl-click two lines. Only the relations that fit are offered (for example Parallel, Equal).
3. **Drag to connect:** on a sketch that is not fully defined yet, drag the end of one line onto another line's end or onto the middle of a curve. A yellow tile shows beside the pointer (Merge or On Edge); let go and the relation is added.
4. **Over-defining:** try to add a relation the sketch already has. It is refused, not added twice.
5. **Dimension it:** **Smart Dimension** a side, type a value, Enter. Blue lines are free to move, **black** ones are fully defined, red ones clash. When nothing can move the status bar says **Fully Defined**. Change a dimension and watch the shape keep its relations.
6. **Display/Delete Relations** (Sketch tab) lists everything, with filters. Delete one and check that the geometry stays where it was.

## Minutes 12 to 15: take it further
Pick one: **Fully Define Sketch**; an **Offset Entities** of what you drew (a **Mirror Entities** too: tick Copy to keep the originals); an **Extruded Boss/Base**, then a **Fillet** on an edge; or Ctrl+S, close, reopen and edit the sketch again. Press **F1** at any time for the page of the built-in guide that fits what you are doing.

## When something is off (copy this block, one per problem)
Send to **[GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues)**. The longer form is `FEEDBACK-TEMPLATE.md`.

```
Add-on version: 0.3.3-alpha     FreeCAD / Windows version:
Steps (what I clicked or typed, in order):
Expected:
Happened instead (stops me / wrong but I can go on / only looks different):
Every time or sometimes:
Screenshot: attached (Win+Shift+S)
File: attached (a small file that shows it; not a confidential model)
Report view text: View, Panels, Report view, right-click, switch on Log messages, repeat the step, copy the lines that mention an error or start with "FreeWorks":
```

Please check `KNOWN-ISSUES.md` first.
