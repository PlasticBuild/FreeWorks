""


import math, os, sys

OUT = sys.argv[1]
INK = "#3c4a60"
GREEN, MAG, RED, ORANGE, BLUE, PURPLE, GOLD, DARK = "#2e9b3e", "#b4288c", "#d8392b", "#e98a12", "#2f6fd0", "#7b3fb5", "#e8b923", "#2b2b2b"


def svg(*parts):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">'
            '<defs><linearGradient id="r" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#2040d0"/>'
            '<stop offset="0.25" stop-color="#20b0e0"/><stop offset="0.5" stop-color="#30c040"/>'
            '<stop offset="0.75" stop-color="#f0e020"/><stop offset="1" stop-color="#e02020"/></linearGradient></defs>'
            + "".join(parts) + "</svg>\n")


def block(x=4, y=14, w=16, d=7, h=9):
    """Isometric box: front-left corner at (x, y + d/2 + h)."""
    t = [(x, y + d / 2), (x + w * 0.6, y), (x + w, y + d / 2 - 0.0), (x + w * 0.4, y + d)]
    tx = [(x, y + d / 2), (x + w * 0.6, y), (x + w + 0, y + d / 2), (x + w * 0.4, y + d)]
    left = [(x, y + d / 2), (x + w * 0.4, y + d), (x + w * 0.4, y + d + h), (x, y + d / 2 + h)]
    right = [(x + w * 0.4, y + d), (x + w, y + d / 2), (x + w, y + d / 2 + h), (x + w * 0.4, y + d + h)]
    return (poly(tx, "#e6edf6") + poly(left, "#b7c6d9") + poly(right, "#97abc4"))


def poly(pts, fill, stroke=INK, sw=1.0):
    return '<polygon points="%s" fill="%s" stroke="%s" stroke-width="%s" stroke-linejoin="round"/>' % (
        " ".join("%.1f,%.1f" % p for p in pts), fill, stroke, sw)


def line(x1, y1, x2, y2, c=INK, w=1.5, dash=None, cap="round"):
    return '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="%s" stroke-linecap="%s"%s/>' % (
        x1, y1, x2, y2, c, w, cap, (' stroke-dasharray="%s"' % dash) if dash else "")


def path(d, c=INK, w=1.5, fill="none"):
    return '<path d="%s" stroke="%s" stroke-width="%s" fill="%s" stroke-linecap="round" stroke-linejoin="round"/>' % (d, c, w, fill)


def circle(x, y, r, fill, c=INK, w=1.0):
    return '<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s" stroke="%s" stroke-width="%s"/>' % (x, y, r, fill, c, w)


def rect(x, y, w, h, fill, c=INK, sw=1.0, rx=0):
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (x, y, w, h, rx, fill, c, sw)


def text(x, y, s, c=DARK, size=9, weight="bold"):
    return '<text x="%.1f" y="%.1f" font-family="Arial, Helvetica, sans-serif" font-size="%s" font-weight="%s" fill="%s" text-anchor="middle">%s</text>' % (x, y, size, weight, c, s)


def arrow(x1, y1, x2, y2, c, w=2.0, head=4.5):
    a = math.atan2(y2 - y1, x2 - x1)
    hx, hy = x2 - head * math.cos(a), y2 - head * math.sin(a)
    p1 = (hx + head * 0.55 * math.sin(a), hy - head * 0.55 * math.cos(a))
    p2 = (hx - head * 0.55 * math.sin(a), hy + head * 0.55 * math.cos(a))
    return line(x1, y1, hx, hy, c, w) + poly([(x2, y2), p1, p2], c, c, 0.8)


def ground(x, y, w, c=GREEN):
    s = line(x, y, x + w, y, c, 1.6)
    for i in range(4):
        xx = x + 1 + i * (w - 2) / 3.0
        s += line(xx, y, xx - 2.5, y + 3, c, 1.2)
    return s


def badge_plus(c=GREEN):
    return circle(25, 25, 5.5, "#ffffff", c, 1.4) + line(22, 25, 28, 25, c, 1.8) + line(25, 22, 25, 28, c, 1.8)


def badge_x():
    return circle(25, 25, 5.5, "#ffffff", RED, 1.4) + line(22.5, 22.5, 27.5, 27.5, RED, 1.8) + line(27.5, 22.5, 22.5, 27.5, RED, 1.8)


def doc(x=6, y=3, w=17, h=24, fill="#ffffff"):
    return poly([(x, y), (x + w - 5, y), (x + w, y + 5), (x + w, y + h), (x, y + h)], fill) + poly(
        [(x + w - 5, y), (x + w - 5, y + 5), (x + w, y + 5)], "#d9dee6")


def mesh(x=4, y=8, w=18, h=16, c=BLUE):
    s = rect(x, y, w, h, "#dfe9f8", c, 1.2)
    for i in range(1, 4):
        s += line(x + i * w / 4.0, y, x + i * w / 4.0, y + h, c, 0.8)
    for i in range(1, 3):
        s += line(x, y + i * h / 3.0, x + w, y + i * h / 3.0, c, 0.8)
    for i in range(4):
        for j in range(3):
            s += line(x + i * w / 4.0, y + j * h / 3.0, x + (i + 1) * w / 4.0, y + (j + 1) * h / 3.0, c, 0.6)
    return s


def rainbow(x=19, y=5, w=6, h=20):
    return rect(x, y, w, h, "url(#r)", INK, 1.0)


def gear(x, y, r=6, c=INK, fill="#c9d3df"):
    pts = []
    for i in range(16):
        a = i * math.pi / 8
        rr = r if i % 2 == 0 else r * 0.75
        pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
    return poly(pts, fill, c, 1.0) + circle(x, y, r * 0.3, "#ffffff", c, 0.8)


def spring(x1, y, x2, c, amp=3, n=6, vertical=False):
    pts = []
    for i in range(n * 2 + 1):
        t = i / float(n * 2)
        off = 0 if i in (0, n * 2) else (amp if i % 2 else -amp)
        pts.append((x1 + (x2 - x1) * t, y + off) if not vertical else (y + off, x1 + (x2 - x1) * t))
    return '<polyline points="%s" fill="none" stroke="%s" stroke-width="1.6" stroke-linejoin="round"/>' % (
        " ".join("%.1f,%.1f" % p for p in pts), c)


def curved(cx, cy, r, a0, a1, c, w=2.0):
    x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
    x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
    large = 1 if abs(a1 - a0) > 180 else 0
    s = path("M%.1f %.1f A%.1f %.1f 0 %d 1 %.1f %.1f" % (x0, y0, r, r, large, x1, y1), c, w)
    a = math.radians(a1 + 90)
    hx, hy = x1, y1
    s += poly([(hx + 4 * math.cos(a), hy + 4 * math.sin(a)), (hx + 2.2 * math.cos(a + 2.0), hy + 2.2 * math.sin(a + 2.0)),
               (hx + 2.2 * math.cos(a - 2.0), hy + 2.2 * math.sin(a - 2.0))], c, c, 0.8)
    return s


def thermometer(x, y, c=RED):
    return rect(x - 2, y, 4, 14, "#ffffff", INK, 1.0, 2) + circle(x, y + 16, 3.5, c, INK, 1.0) + rect(x - 0.9, y + 5, 1.8, 10, c, c, 0.5)


def ibeam(x, y, s=1.0, c="#9fb1c7"):
    return poly([(x, y), (x + 14 * s, y), (x + 14 * s, y + 3 * s), (x + 8.5 * s, y + 3 * s), (x + 8.5 * s, y + 13 * s),
                 (x + 14 * s, y + 13 * s), (x + 14 * s, y + 16 * s), (x, y + 16 * s), (x, y + 13 * s), (x + 5.5 * s, y + 13 * s),
                 (x + 5.5 * s, y + 3 * s), (x, y + 3 * s)], c)


def frame(x, y, cells, w=7):
    s = ""
    for i, t in enumerate(cells):
        s += rect(x + i * w, y, w, 8, "#ffffff", DARK, 1.0) + text(x + i * w + w / 2.0, y + 6.5, t, DARK, 6.5)
    return s


def dimline(x1, y, x2, c=DARK):
    return (line(x1, y - 4, x1, y + 4, c, 1) + line(x2, y - 4, x2, y + 4, c, 1) + arrow(x1 + 7, y, x1 + 0.5, y, c, 1.2, 3.5)
            + arrow(x2 - 7, y, x2 - 0.5, y, c, 1.2, 3.5) + line(x1 + 6, y, x2 - 6, y, c, 1.2))


B = block()
ICONS = {
    # ------------------------------------------------------------------ studies
    "SIM_NewStudy": doc() + block(9, 12, 11, 5, 6) + poly([(24, 2), (25.5, 6), (30, 6), (26.5, 8.5), (28, 13), (24, 10.3), (20, 13), (21.5, 8.5), (18, 6), (22.5, 6)], GOLD, "#a07800", 0.8),
    "SIM_Advisor": block(2, 14) + circle(24, 10, 6.5, "#fff6c8", "#a07800", 1.2) + text(24, 14, "?", "#a07800", 10),
    "SIM_Props": doc() + "".join(line(9, 10 + i * 4, 20, 10 + i * 4, INK, 1.2) for i in range(4)) + gear(23, 23, 6),
    "SIM_Wizard": block(2, 15) + line(14, 22, 27, 6, "#6b4a2b", 2.4) + poly([(27, 2), (28, 5), (31, 5), (28.6, 7), (29.5, 10), (27, 8.2), (24.5, 10), (25.4, 7), (23, 5), (26, 5)], GOLD, "#a07800", 0.7),
    "SIM_Duplicate": doc(3, 2, 15, 21, "#eef2f7") + doc(11, 8, 15, 21),
    "SIM_Analysis": doc() + block(9, 13, 11, 5, 6),
    "SIM_ApplyMaterial": block(2, 15) + circle(23, 10, 7, "#d9a441", INK, 1) + path("M18 7 Q23 4 28 7", "#ffffff", 1.2) + path("M17 11 L29 11", "#b07b20", 1),
    "SIM_MaterialNonlinear": rect(3, 3, 26, 26, "#ffffff", INK, 1) + line(6, 26, 6, 6, INK, 1) + line(6, 26, 27, 26, INK, 1) + path("M6 26 L13 12 Q18 6 27 6", RED, 1.8),
    "SIM_MaterialReinforced": block(3, 10, 20, 8, 12) + "".join(circle(9 + i * 4, 24 - i * 1.6, 1.4, DARK, DARK) for i in range(3)),
    # ------------------------------------------------------------------ fixtures (green)
    "SIM_Fixed": B + "".join(arrow(8 + i * 5, 32, 8 + i * 5, 26, GREEN, 1.6, 3.5) for i in range(3)) + ground(4, 30, 18),
    "SIM_Roller": B + circle(9, 29, 2.3, "#ffffff", GREEN, 1.4) + circle(16, 29, 2.3, "#ffffff", GREEN, 1.4) + line(4, 31.5, 22, 31.5, GREEN, 1.4),
    "SIM_Hinge": B + circle(24, 12, 5, "#ffffff", GREEN, 1.8) + circle(24, 12, 1.6, GREEN, GREEN) + curved(24, 12, 7.5, 200, 330, GREEN, 1.4),
    "SIM_Elastic": B + spring(8, 26, 32, GREEN, 2, 3, True) + spring(16, 26, 32, GREEN, 2, 3, True) + line(4, 31.5, 22, 31.5, GREEN, 1.4),
    "SIM_Rigid": block(1, 15, 12, 5, 7) + block(17, 6, 12, 5, 7) + line(8, 18, 23, 10, GREEN, 2.4) + circle(8, 18, 1.8, GREEN, GREEN) + circle(23, 10, 1.8, GREEN, GREEN),
    # ------------------------------------------------------------------ loads (magenta)
    "SIM_Force": block(2, 15) + arrow(28, 3, 16, 16, MAG, 2.4, 5.5),
    "SIM_Pressure": block(2, 15) + "".join(arrow(10 + i * 6, 2, 10 + i * 6, 15 - i * 1.2, MAG, 1.6, 3.8) for i in range(3)),
    "SIM_Gravity": B + arrow(26, 3, 26, 27, MAG, 2.2, 5) + text(20, 9, "g", MAG, 10),
    "SIM_Centrifugal": B + line(12, 2, 12, 30, DARK, 1, "2,2") + curved(12, 8, 7, 200, 520, MAG, 1.8),
    "SIM_Bearing": circle(14, 17, 10, "#c9d3df", INK, 1.2) + circle(14, 17, 5, "#ffffff", INK, 1.2) + "".join(arrow(14 + 7 * math.cos(math.radians(a)), 17 + 7 * math.sin(math.radians(a)), 14 + 5 * math.cos(math.radians(a)), 17 + 5 * math.sin(math.radians(a)) , MAG, 1.4, 2.5) for a in (60, 90, 120)) + arrow(14, 2, 14, 9, MAG, 2, 4),
    "SIM_Temperature": B + thermometer(26, 4),
    "SIM_HeatFlux": B + "".join(path("M%d 2 q2 2 0 4 q-2 2 0 4 q2 2 0 4" % (10 + i * 6), RED, 1.5) for i in range(3)) + "".join(poly([(10 + i * 6, 17), (8 + i * 6, 14), (12 + i * 6, 14)], RED, RED, 0.6) for i in range(3)),
    "SIM_BodyHeat": B + circle(24, 9, 4, "#ffd040", RED, 1.2) + "".join(line(24 + 5.5 * math.cos(a), 9 + 5.5 * math.sin(a), 24 + 8 * math.cos(a), 9 + 8 * math.sin(a), RED, 1.4) for a in [i * math.pi / 4 for i in range(8)]),
    "SIM_InitialTemp": B + thermometer(26, 4, BLUE) + text(19, 9, "0", BLUE, 8),
    # ------------------------------------------------------------------ connections (orange)
    "SIM_Contact": block(2, 4, 14, 6, 7) + block(2, 17, 14, 6, 7) + line(4, 18, 18, 18, ORANGE, 2.2) + path("M22 12 l4 -4 m-4 4 l5 1 m-5 -1 l1 5", ORANGE, 1.6),
    "SIM_Bonded": block(2, 4, 14, 6, 7) + block(2, 17, 14, 6, 7) + "".join(circle(5 + i * 4, 19.5 - i * 0.9, 1.4, ORANGE, ORANGE) for i in range(4)),
    "SIM_Spring": block(6, 2, 14, 6, 7) + spring(16, 13, 30, ORANGE, 3, 4, True) + line(6, 30.5, 24, 30.5, ORANGE, 1.6),
    "SIM_Shell": poly([(3, 18), (17, 10), (29, 15), (15, 23)], "#cfdcef") + poly([(3, 21), (17, 13), (29, 18), (15, 26)], "none", BLUE, 1) + line(15, 23, 15, 26, BLUE, 1),
    "SIM_Beam": ibeam(9, 8),
    "SIM_BeamRotation": ibeam(5, 10, 0.8) + curved(14, 16, 12, 260, 350, MAG, 1.6),
    # ------------------------------------------------------------------ mesh (blue)
    "SIM_Diagnostic": mesh(2, 4, 18, 16) + circle(21, 20, 6, "#ffffff", DARK, 2) + line(25.5, 24.5, 30, 29, DARK, 2.6),
    "SIM_MeshInfo": mesh(2, 4, 18, 16) + circle(24, 23, 6, "#ffffff", BLUE, 1.4) + text(24, 27, "i", BLUE, 9),
    "SIM_Mesh": mesh(4, 7, 22, 18),
    "SIM_MeshNetgen": mesh(2, 4, 20, 17) + circle(25, 25, 6, "#ffffff", BLUE, 1.4) + text(25, 28.5, "N", BLUE, 9),
    "SIM_MeshControl": mesh(4, 7, 22, 18) + circle(8, 11, 3.5, "none", RED, 1.6) + circle(8, 11, 1, RED, RED),
    "SIM_MeshBoundary": rect(4, 5, 22, 20, "#dfe9f8", BLUE, 1.2) + "".join(line(4, 25 - i * (1.2 + i), 26, 25 - i * (1.2 + i), BLUE, 0.9) for i in range(1, 5)),
    "SIM_MeshClear": mesh(2, 4, 20, 17) + badge_x(),
    # ------------------------------------------------------------------ run and solvers
    "SIM_Run": block(2, 15) + poly([(17, 2), (29, 9), (17, 16)], GREEN, "#1d6b2a", 1.2),
    "SIM_RunAll": block(1, 16, 12, 5, 7) + poly([(14, 3), (23, 9), (14, 15)], GREEN, "#1d6b2a", 1) + poly([(20, 3), (29, 9), (20, 15)], GREEN, "#1d6b2a", 1),
    "SIM_SolverCcx": gear(13, 14, 10) + text(24, 29, "C", DARK, 11),
    "SIM_SolverElmer": gear(13, 14, 10) + text(24, 29, "E", DARK, 11),
    "SIM_SolverZ88": gear(13, 14, 10) + text(23, 29, "Z", DARK, 11),
    "SIM_SolverMystran": gear(13, 14, 10) + text(24, 29, "M", DARK, 11),
    "SIM_SolverControl": doc() + gear(22, 22, 7),
    # ------------------------------------------------------------------ results (rainbow)
    "SIM_Results": block(1, 14, 15) + rainbow(21, 4, 7, 24),
    "SIM_Plot": block(1, 14, 14) + rainbow(18, 2, 6, 16) + badge_plus(),
    "SIM_ApplyChanges": block(1, 14, 14) + rainbow(18, 2, 6, 16) + curved(25, 25, 4.5, 200, 520, BLUE, 1.6),
    "SIM_Purge": block(1, 14, 14) + rainbow(18, 2, 6, 16) + badge_x(),
    "SIM_Deform": path("M3 20 Q10 12 16 18 T29 14 L29 22 Q22 26 16 25 T3 27 Z", "#ff9a3a", 1.2, "#ffcf8f") + path("M3 20 L29 20", INK, 1, "none").replace('stroke-linecap="round"', 'stroke-dasharray="2,2"'),
    "SIM_Compare": rect(2, 6, 13, 20, "#ffffff", INK, 1) + rainbow(5, 9, 7, 14) + rect(17, 6, 13, 20, "#ffffff", INK, 1) + rainbow(20, 9, 7, 14),
    "SIM_IsoClip": block(1, 12, 18) + poly([(1, 21), (11, 27), (19, 22), (19, 17), (1, 15)], "url(#r)", INK, 0.8),
    "SIM_PlotTools": block(1, 14, 14) + rainbow(18, 2, 6, 14) + path("M22 21 l7 7 m-9 -5 a3 3 0 1 1 4 -4", DARK, 2),
    "SIM_Section": block(2, 10, 20, 8, 14) + poly([(13, 4), (27, 9), (27, 29), (13, 24)], "#f2b9b9", RED, 1).replace('fill="#f2b9b9"', 'fill="#f2b9b9" fill-opacity="0.75"'),
    "SIM_Probe": block(1, 14, 15) + rainbow(21, 3, 6, 16) + line(10, 18, 28, 30, DARK, 1.3) + circle(10, 18, 2, "#ffffff", RED, 1.6),
    "SIM_ListLine": line(3, 26, 29, 6, BLUE, 1.6) + "".join(circle(3 + i * 6.5, 26 - i * 5, 1.8, "#ffffff", BLUE, 1.2) for i in range(5)),
    "SIM_Linearized": rect(3, 3, 26, 26, "#ffffff", INK, 1) + path("M5 24 L27 8", RED, 1.6) + path("M5 20 L27 20", BLUE, 1.6) + path("M5 27 L27 5", DARK, 0.8),
    "SIM_Report": doc() + rect(9, 15, 3, 8, "#4b8fd8", INK, 0.6) + rect(13, 11, 3, 12, "#e2543e", INK, 0.6) + rect(17, 17, 3, 6, "#46a85a", INK, 0.6),
    "SIM_ReportImage": doc() + rect(17, 15, 13, 11, "#cfe3fb", INK, 1) + poly([(18, 25), (22, 19), (25, 23), (27, 21), (29, 25)], "#46a85a", "#2e7d3e", 0.6) + circle(26.5, 18, 1.4, GOLD, GOLD),
    "SIM_AllTools": rect(3, 3, 12, 12, "#e6edf6", INK, 1) + rect(17, 3, 12, 12, "#d6f0da", INK, 1) + rect(3, 17, 12, 12, "#f8dcef", INK, 1) + rect(17, 17, 12, 12, "#dfe9f8", INK, 1),
    # ------------------------------------------------------------------ MBD
    "MBD_CopyScheme": doc(2, 2, 15, 21, "#eef2f7") + doc(12, 9, 15, 21) + dimline(13, 22, 26),
    "MBD_AutoPair": frame(2, 4, ("⌖", "A")) + frame(14, 20, ("⌖", "B")) + path("M9 12 C9 20 14 18 18 20", INK, 1.2),
    "MBD_SurfaceFinish": path("M4 18 L9 26 L19 6 L29 6", DARK, 1.8) + line(4, 28, 29, 28, DARK, 1.2),
    "MBD_Weld": line(2, 22, 22, 22, DARK, 1.4) + poly([(10, 22), (16, 22), (13, 16)], DARK, DARK, 0.8) + arrow(22, 22, 29, 29, DARK, 1.2, 3.5),
    "MBD_Note": rect(10, 3, 19, 14, "#ffffff", DARK, 1.2) + text(19.5, 13.5, "A", DARK, 10) + arrow(12, 17, 3, 28, DARK, 1.2, 4),
    "MBD_RefDim": dimline(3, 10, 29) + text(16, 7, "25", DARK, 7) + block(6, 16, 20, 6, 7),
    "MBD_Capture": rect(3, 10, 24, 16, "#5d6b80", DARK, 1, 2) + circle(15, 18, 5.5, "#cfe3fb", DARK, 1.4) + rect(8, 7, 7, 4, "#5d6b80", DARK, 1),
    "MBD_Views": rect(9, 3, 20, 15, "#ffffff", INK, 1) + rect(6, 7, 20, 15, "#ffffff", INK, 1) + rect(3, 11, 20, 15, "#e6edf6", INK, 1) + block(7, 14, 11, 4, 5),
    "ModelBreakView": block(2, 10, 26, 8, 10) + path("M14 6 l2 3 l-2 3 l2 3 l-2 3 l2 3 l-2 3", RED, 1.6) + path("M18 4 l2 3 l-2 3 l2 3 l-2 3 l2 3 l-2 3", RED, 1.6),
    "MBD_Dynamic": path("M2 16 Q16 4 30 16 Q16 28 2 16 Z", DARK, 1.4, "#ffffff") + circle(16, 16, 5, "#4b8fd8", DARK, 1) + frame(16, 22, ("A",)),
    "MBD_PDFTemplate": doc() + "".join(line(8 + i * 4, 9, 8 + i * 4, 25, "#9aa8bb", 0.8) for i in range(4)) + "".join(line(7, 11 + i * 4, 22, 11 + i * 4, "#9aa8bb", 0.8) for i in range(4)),
    "MBD_PDF": doc() + rect(3, 16, 24, 9, "#d8392b", "#9e2016", 1, 1) + text(15, 23.5, "PDF", "#ffffff", 7.5),
    "MBD_STEP": doc() + rect(3, 16, 24, 9, "#2f6fd0", "#1d4f9e", 1, 1) + text(15, 23.5, "242", "#ffffff", 7.5),
    "MBD_Compare": doc(2, 3, 13, 19, "#eef2f7") + doc(17, 10, 13, 19) + arrow(9, 26, 20, 26, BLUE, 1.4, 3.5) + arrow(24, 6, 13, 6, BLUE, 1.4, 3.5),
    # ------------------------------------------------------------------ MotionManager
    "MOTION_CALCULATE": block(2, 14) + circle(23, 10, 7, "#ffffff", BLUE, 1.6) + line(23, 10, 23, 5.5, BLUE, 1.5) + line(23, 10, 26.5, 12, BLUE, 1.5),
    "MOTION_PLAY_FROM_START": rect(5, 7, 3, 18, BLUE, "#1d4f9e", 0.8) + poly([(10, 16), (26, 7), (26, 25)], BLUE, "#1d4f9e", 1).replace("10.0,16.0 26.0,7.0 26.0,25.0", "26.0,16.0 10.0,7.0 10.0,25.0"),
    "MOTION_PLAY": poly([(8, 5), (27, 16), (8, 27)], BLUE, "#1d4f9e", 1.2),
    "MOTION_STOP": rect(7, 7, 18, 18, BLUE, "#1d4f9e", 1.2, 1.5),
    "MOTION_SAVE_ANIMATION": rect(3, 6, 22, 16, "#3b3f46", DARK, 1) + "".join(rect(5 + i * 5, 7.5, 2.5, 2, "#ffffff", "#ffffff", 0.3) + rect(5 + i * 5, 18.5, 2.5, 2, "#ffffff", "#ffffff", 0.3) for i in range(4)) + rect(18, 18, 12, 12, "#2f6fd0", "#1d4f9e", 1) + rect(21, 18, 6, 4, "#ffffff", "#ffffff", 0.3),
    "MOTION_WIZARD": rect(2, 12, 18, 14, "#3b3f46", DARK, 1) + line(14, 24, 27, 8, "#6b4a2b", 2.4) + poly([(27, 2), (28, 5), (31, 5), (28.6, 7), (29.5, 10), (27, 8.2), (24.5, 10), (25.4, 7), (23, 5), (26, 5)], GOLD, "#a07800", 0.7),
    "MOTION_AUTOKEY": circle(10, 16, 6, "#ffffff", GOLD, 2.2) + line(16, 16, 29, 16, GOLD, 2.4) + line(25, 16, 25, 21, GOLD, 2.2) + line(28, 16, 28, 20, GOLD, 2.2) + text(10, 19.5, "A", "#a07800", 8),
    "MOTION_ADD_KEY": circle(9, 12, 5.5, "#ffffff", GOLD, 2.2) + line(14.5, 12, 26, 12, GOLD, 2.4) + line(22, 12, 22, 17, GOLD, 2.2) + badge_plus(GREEN),
    "MOTION_MOTOR": block(2, 15) + line(24, 2, 24, 30, DARK, 1.2, "2,2") + curved(24, 12, 6, 210, 500, RED, 2),
    "MOTION_SPRING": block(1, 2, 12, 5, 6) + spring(12, 16, 30, "#4b5563", 3.5, 5, True) + line(8, 30.5, 24, 30.5, DARK, 1.6),
    "MOTION_DAMPER": block(1, 2, 12, 5, 6) + line(16, 13, 16, 19, DARK, 1.6) + rect(11, 19, 10, 9, "#c9d3df", DARK, 1.2) + line(12, 22, 20, 22, DARK, 1.6) + line(16, 28, 16, 31, DARK, 1.6),
    "MOTION_FORCE": block(2, 15) + arrow(28, 3, 16, 16, MAG, 2.4, 5.5),
    "MOTION_CONTACT": block(1, 14, 13, 6, 8) + circle(22, 12, 7, "#c9d3df", INK, 1.2) + path("M14 19 l3 -2 m-3 2 l1 3 m-1 -3 l4 1", ORANGE, 1.6),
    "MOTION_GRAVITY": B + arrow(26, 3, 26, 27, MAG, 2.2, 5) + text(20, 9, "g", MAG, 10),
    "MOTION_RESULTS": rect(3, 3, 26, 26, "#ffffff", INK, 1) + line(6, 26, 6, 6, INK, 1) + line(6, 26, 27, 26, INK, 1) + path("M6 20 Q11 6 16 16 T27 10", RED, 1.8),
    "MOTION_STUDY_PROPERTIES": doc() + "".join(line(9, 10 + i * 4, 20, 10 + i * 4, INK, 1.2) for i in range(4)) + gear(23, 23, 6),
    "MOTION_COLLAPSE": rect(3, 4, 26, 24, "#ffffff", INK, 1) + path("M9 19 L16 12 L23 19", BLUE, 2.4),
}
def stream(y, c=BLUE, x0=2, x1=26):
    return path("M%d %d C%d %d %d %d %d %d" % (x0, y, x0 + 8, y - 4, x1 - 8, y + 4, x1, y), c, 1.6) + poly([(x1 + 3, y), (x1 - 1, y - 2.5), (x1 - 1, y + 2.5)], c, c, 0.6)


FLOWS = "".join(stream(y) for y in (8, 15, 22))
ICONS.update({
    "FLOW_New": doc() + stream(17, BLUE, 8, 18) + poly([(24, 2), (25.5, 6), (30, 6), (26.5, 8.5), (28, 13), (24, 10.3), (20, 13), (21.5, 8.5), (18, 6), (22.5, 6)], GOLD, "#a07800", 0.8),
    "FLOW_Clone": doc(3, 2, 15, 21, "#eef2f7") + doc(11, 8, 15, 21) + stream(20, BLUE, 13, 21),
    "FLOW_Equation": rect(3, 5, 26, 22, "#ffffff", INK, 1) + text(16, 21, "∇·u", BLUE, 11),
    "FLOW_Project": doc() + gear(23, 23, 6) + stream(12, BLUE, 8, 17),
    "FLOW_Heat": block(2, 15) + "".join(path("M%d 2 q2 2 0 4 q-2 2 0 4" % (14 + i * 6), RED, 1.5) for i in range(3)) + arrow(4, 8, 12, 8, RED, 1.4, 3.5),
    "FLOW_Velocity": rect(2, 6, 7, 20, "#cfdcef", INK, 1) + FLOWS.replace("M2 ", "M10 "),
    "FLOW_Pressure": rect(2, 3, 28, 26, "#e7f0fb", BLUE, 1) + "".join(arrow(16, 16, 16 + 10 * c, 16 + 10 * s, MAG, 1.6, 3.5) for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1))),
    "FLOW_InitVel": FLOWS + text(27, 30, "0", DARK, 9),
    "FLOW_InitPress": rect(2, 3, 24, 22, "#e7f0fb", BLUE, 1) + "".join(arrow(14, 14, 14 + 8 * c, 14 + 8 * s, MAG, 1.4, 3) for c, s in ((1, 0), (-1, 0), (0, 1), (0, -1))) + text(27, 31, "0", DARK, 9),
    "FLOW_Sources": B + circle(24, 9, 5, "#ffffff", RED, 1.4) + line(24, 6.5, 24, 11.5, RED, 1.6) + line(21.5, 9, 26.5, 9, RED, 1.6),
    "FLOW_Mesh": mesh(2, 4, 20, 17) + stream(26, BLUE, 4, 26),
    "FLOW_BatchRun": "".join(rect(3 + i * 3, 3 + i * 3, 16, 12, "#ffffff", INK, 1) for i in range(3)) + poly([(17, 15), (29, 22), (17, 29)], GREEN, "#1d6b2a", 1.2),
    "FLOW_Results": FLOWS.replace(BLUE, "#20b0e0") + rainbow(26, 3, 5, 26),
    "FLOW_Capture": rect(3, 10, 24, 16, "#5d6b80", DARK, 1, 2) + circle(15, 18, 5.5, "#cfe3fb", DARK, 1.4) + rect(8, 7, 7, 4, "#5d6b80", DARK, 1) + stream(18, BLUE, 10, 18),
    "FLOW_EngDB": path("M5 7 A11 4 0 0 0 27 7 L27 25 A11 4 0 0 1 5 25 Z", INK, 1.2, "#dfe9f8") + path("M5 7 A11 4 0 0 1 27 7", INK, 1.2) + path("M5 13 A11 4 0 0 0 27 13 M5 19 A11 4 0 0 0 27 19", INK, 1),
    "FLOW_Fluid": path("M16 3 C22 12 26 16 26 21 A10 10 0 0 1 6 21 C6 16 10 12 16 3 Z", "#1d4f9e", 1.2, "#5aa4f0") + path("M11 21 A5 5 0 0 0 15 26", "#ffffff", 1.6),
    "FLOW_AllTools": rect(3, 3, 12, 12, "#e6edf6", INK, 1) + rect(17, 3, 12, 12, "#dfe9f8", INK, 1) + rect(3, 17, 12, 12, "#dfe9f8", INK, 1) + rect(17, 17, 12, 12, "#e6edf6", INK, 1) + stream(9, BLUE, 4, 12),
})
ICONS.update({
    "SIM_Interaction": block(1, 4, 14, 6, 7) + block(13, 15, 14, 6, 7) + path("M6 22 l4 4 l8 -8", ORANGE, 2.2) + circle(24, 8, 4.5, "#ffffff", ORANGE, 1.6) + line(21.5, 8, 26.5, 8, ORANGE, 1.6),
    "SIM_Bolt": rect(3, 12, 26, 5, "#c9d3df", INK, 1) + rect(3, 19, 26, 5, "#b7c6d9", INK, 1) + rect(13, 5, 6, 24, "#7f8b99", DARK, 1) + rect(10, 3, 12, 4, "#5d6b80", DARK, 1) + rect(10, 26, 12, 4, "#5d6b80", DARK, 1) + "".join(line(13, 9 + i * 3, 19, 10.5 + i * 3, "#d8dee6", 0.8) for i in range(6)),
    "SIM_Pin": rect(3, 9, 12, 14, "#c9d3df", INK, 1) + rect(17, 9, 12, 14, "#b7c6d9", INK, 1) + rect(1, 14, 30, 4, "#7f8b99", DARK, 1) + circle(16, 16, 1.4, ORANGE, ORANGE),
    "SIM_SpringConnector": rect(3, 3, 26, 5, "#c9d3df", INK, 1) + rect(3, 24, 26, 5, "#b7c6d9", INK, 1) + spring(8, 16, 24, ORANGE, 4, 4, True),
    # PM pkg356 / 357 / 358 commands (addintabs-104)
    "SIM_Torque": B + line(12, 2, 12, 30, DARK, 1, "2,2") + curved(12, 10, 6, 210, 480, MAG, 2.2) + arrow(23, 3, 18.5, 6.5, MAG, 0.1, 4.5),
    "SIM_RemoteLoad": B + line(14, 14, 25, 5, GREEN, 1.4, "2,1.5") + circle(25, 5, 2.4, "#ffffff", MAG, 1.4) + arrow(25, 5, 30, 14, MAG, 1.8, 3.5),
    "SIM_DistributedMass": block(2, 15) + "".join(rect(4.5 + i * 5.5, 7.5 - i * 1.2, 4, 4, "#5d6b80", DARK, 0.8) + arrow(6.5 + i * 5.5, 11.5 - i * 1.2, 6.5 + i * 5.5, 16.5 - i * 1.0, MAG, 1.2, 2.5) for i in range(3)),
    "SIM_BearingConnector": circle(16, 16, 12, "#c9d3df", INK, 1.2) + circle(16, 16, 8, "#ffffff", INK, 1) + "".join(circle(16 + 10 * math.cos(a), 16 + 10 * math.sin(a), 1.5, ORANGE, ORANGE, 0.6) for a in [k * math.pi / 4 for k in range(8)]) + circle(16, 16, 5, "#7f8b99", DARK, 1),
    "SIM_RigidConnector": rect(2, 12, 11, 12, "#c9d3df", INK, 1) + rect(19, 6, 11, 12, "#b7c6d9", INK, 1) + line(10, 18, 22, 12, ORANGE, 2.6) + circle(10, 18, 1.8, ORANGE, ORANGE) + circle(22, 12, 1.8, ORANGE, ORANGE),
    "SIM_MeshQuality": mesh(2, 6, 20, 18) + rainbow(24, 4, 5, 22),
})
ICONS.update({
    # New Study's types: the study icon with the type's mark
    "SIM_Static": B + arrow(26, 3, 26, 13, MAG, 2.2) + ground(4, 29, 18),
    "SIM_Thermal": B + thermometer(26, 4) + path("M4 6 q2 -3 4 0 q2 3 4 0", RED, 1.5),
    "SIM_Frequency": B + path("M2 6 Q5 0 8 6 T14 6 T20 6 T26 6 T32 6", PURPLE, 1.8),
    "SIM_Buckling": rect(13, 6, 6, 24, "#c9d3df", INK, 1) + path("M16 6 Q24 18 16 30", PURPLE, 2.0) + arrow(16, 0.5, 16, 6, MAG, 2.0, 3.5) + ground(8, 30.5, 16),
    "SIM_Fatigue": B + path("M2 4 L6 10 L10 4 L14 10 L18 4 L22 10 L26 4 L30 10", MAG, 1.5) + path("M12 20 l3 -2 l-1 3 l3 -2", RED, 1.4),
    "SIM_DropTest": block(6, 3, 14, 6, 7) + arrow(13, 17, 13, 25, BLUE, 2.0, 4) + rect(2, 27, 28, 3, "#7f8b99", DARK, 1),
    "SIM_DesignStudy": "".join(rect(2 + c * 6, 3 + r * 5, 6, 5, "#ffffff" if r else "#dfe9f8", INK, 0.8) for r in range(4) for c in range(3)) + path("M20 26 L24 18 L28 22 L31 12", GREEN, 2.0),
    # Thermal Loads
    "SIM_Convection": B + "".join(path("M%d 13 q-3 -3 0 -6 q3 -3 0 -6" % (9 + i * 6), BLUE, 1.5) for i in range(3)),
    "SIM_Radiation": B + "".join(line(16, 7, 16 + 11 * math.cos(math.radians(a)), 7 - 6 * math.sin(math.radians(a)), RED, 1.3) for a in (0, 35, 70, 110, 145, 180)) + circle(16, 7, 2.2, GOLD, "#a07800", 0.8),
    "SIM_FatigueEvent": doc() + path("M8 16 L11 11 L14 16 L17 11 L20 16", MAG, 1.5) + text(15, 25, "n", DARK, 8),
})
ICONS.update({
    # Sketch Ink and Sketch buttons the icon pack has no picture for
    "PenTouch": path("M3 26 C8 18 12 24 17 15", BLUE, 2.0) + path("M20 30 L20 16 a2 2 0 0 1 4 0 L24 22 L28 23 a2 2 0 0 1 2 2 L29 30 Z", INK, 1.2, "#f4d8b8") + line(22, 9, 22, 12, INK, 1.2) + line(17, 11, 19, 13, INK, 1.2) + line(27, 11, 25, 13, INK, 1.2),
    "PenAutoShape": path("M4 20 C4 8 18 4 22 12 C26 20 14 28 8 24", "#9aa8b8", 1.6, "none").replace('stroke-linecap', 'stroke-dasharray="2 2" stroke-linecap') + circle(19, 17, 9, "none", BLUE, 2.0) + arrow(6, 28, 13, 23, GREEN, 1.6, 3.5),
    "PenAutoSketchEntities": path("M3 22 C6 12 9 26 13 16", "#9aa8b8", 1.6) + arrow(13, 18, 18, 18, GREEN, 1.6, 3.5) + line(18, 26, 24, 14, BLUE, 2.0) + path("M24 14 A6 6 0 0 1 30 20", BLUE, 2.0) + circle(18, 26, 1.6, "#ffffff", BLUE, 1.0) + circle(24, 14, 1.6, "#ffffff", BLUE, 1.0),
    "Instant2D": line(5, 22, 27, 22, BLUE, 1.6) + line(5, 13, 5, 25, INK, 1.0) + line(27, 13, 27, 25, INK, 1.0) + arrow(15, 17, 6, 17, INK, 1.2, 3.2) + arrow(17, 17, 26, 17, INK, 1.2, 3.2) + rect(10, 4, 12, 8, "#ffffff", INK, 1.0, 1) + text(16, 10.5, "25", DARK, 7) + path("M24 26 l4 3 l-2 0.5 l1.5 2.5 l-1 0.6 l-1.5 -2.5 l-1.5 1.5 Z", DARK, 0.8, "#ffffff"),
})
def balloon(x, y, n, r=4.6, c=BLUE):
    return circle(x, y, r, "#ffffff", c, 1.4) + text(x, y + 2.6, n, c, 7)


GRID = rect(3, 6, 24, 20, "#ffffff", INK, 1) + "".join(line(3, 6 + 5 * i, 27, 6 + 5 * i, INK, 0.7) for i in range(1, 4)) + line(11, 6, 11, 26, INK, 0.7) + rect(3, 6, 24, 5, "#dfe9f8", INK, 1)
ICONS.update({
    # the Inspection tab (drawings)
    "INSP_Create": doc() + line(9, 12, 15, 12, INK, 1) + line(9, 16, 18, 16, INK, 1) + balloon(17, 22, "1") + badge_plus(),
    "INSP_Template": doc() + balloon(12, 12, "1") + line(8, 20, 18, 20, INK, 1) + gear(23, 23, 6),
    "INSP_Edit": doc() + "".join(balloon(10, 9 + 7 * i, str(i + 1), 2.8) + line(14, 9 + 7 * i, 19, 9 + 7 * i, INK, 1) for i in range(3)) + path("M18 28 L28 18 L30 20 L20 30 Z", "#7a5a10", 0.9, GOLD),
    "INSP_Add": line(4, 26, 12, 18, INK, 1.2) + balloon(16, 14, "4", 6.5) + badge_plus(),
    "INSP_Update": balloon(10, 10, "2", 5.8) + path("M17 26 A7 7 0 1 0 15 19", GREEN, 2.0) + poly([(11.5, 17), (17.5, 16.5), (15, 22)], GREEN, GREEN, 0.8),
    "INSP_Balloon": "".join(line(5 + 8 * i, 28, 8 + 8 * i, 18, INK, 1) + balloon(8 + 8 * i, 13, str(i + 1), 4.2) for i in range(3)),
    "INSP_RemoveBalloons": line(4, 26, 12, 18, INK, 1.2) + balloon(16, 14, "1", 6.5) + badge_x(),
    "INSP_Report": GRID + path("M14 15 l2 2 l4 -4", GREEN, 1.6) + path("M14 20 l2 2 l4 -4", GREEN, 1.6) + line(15, 24.5, 21, 24.5, RED, 1.6),
    "INSP_Excel": GRID + rect(14, 18, 17, 11, GREEN, "#1d6b2a", 1, 1.5) + text(22.5, 26.5, "xlsx", "#ffffff", 6.5),
    "INSP_Csv": GRID + rect(16, 18, 15, 11, "#5d6b80", DARK, 1, 1.5) + text(23.5, 26.5, "csv", "#ffffff", 7),
    "INSP_Pdf": doc() + balloon(12, 11, "1", 3.6) + rect(13, 18, 18, 11, RED, "#8a1a12", 1, 1.5) + text(22, 26.5, "PDF", "#ffffff", 7),
    "INSP_Delete": doc() + balloon(13, 13, "1", 4.6) + line(9, 21, 19, 21, INK, 1) + badge_x(),
})
FOLDER_Y, FOLDER_E = "#f3c652", "#a87a12"
ICONS.update({
    # Home dialog, Recent Documents, the Comments editor and the Insert > Tables / Mate Reference PMs
    "FW_Folder": path("M3 9 L3 26 L29 26 L29 11 L15 11 L12 8 L4 8 Z", FOLDER_E, 1.1, FOLDER_Y) + line(3.5, 13, 28.5, 13, "#fbe3a0", 1.2),
    "FW_FolderOpen": path("M3 9 L3 26 L26 26 L26 11 L15 11 L12 8 L4 8 Z", FOLDER_E, 1.1, "#e0ae3a") + path("M3 26 L8 15 L31 15 L26 26 Z", FOLDER_E, 1.1, FOLDER_Y),
    "FW_Document": doc() + line(9, 11, 17, 11, "#8a9ab0", 1) + line(9, 15, 19, 15, "#8a9ab0", 1) + block(9, 17, 12, 5, 5),
    "FW_Help": circle(16, 16, 12, BLUE, "#1d4f9e", 1.2) + text(16, 21.5, "?", "#ffffff", 16),
    "FW_Forum": path("M3 5 L20 5 Q22 5 22 7 L22 15 Q22 17 20 17 L10 17 L6 21 L6 17 L5 17 Q3 17 3 15 L3 7 Q3 5 5 5 Z", "#1d4f9e", 1.1, "#dfe9f8")
                + path("M12 13 L27 13 Q29 13 29 15 L29 23 Q29 25 27 25 L26 25 L26 29 L22 25 L14 25 Q12 25 12 23 Z", "#1d6b2a", 1.1, "#e3f2e1"),
    "FW_WhatsNew": poly([(16 + (12 if i % 2 == 0 else 5.5) * math.cos(math.radians(-90 + i * 36)),
                          16 + (12 if i % 2 == 0 else 5.5) * math.sin(math.radians(-90 + i * 36))) for i in range(10)], GOLD, "#a87a12", 1.1),
    "FW_Save": rect(4, 4, 24, 24, BLUE, "#1d4f9e", 1.1, 2) + rect(9, 4, 14, 9, "#ffffff", "#1d4f9e", 0.9) + rect(18, 5.5, 3, 6, "#1d4f9e", "#1d4f9e", 0.5) + rect(8, 17, 16, 11, "#dfe9f8", "#1d4f9e", 0.9),
    "FW_Stamp": rect(3, 6, 18, 18, "#ffffff", INK, 1) + rect(3, 6, 18, 5, RED, "#8a1a12", 1) + text(12, 21.5, "19", DARK, 8)
                + circle(23, 22, 7, "#ffffff", BLUE, 1.4) + line(23, 22, 23, 17.5, BLUE, 1.4) + line(23, 22, 26, 23.5, BLUE, 1.4),
    "FW_Capture": rect(3, 10, 26, 17, "#5d6b80", DARK, 1.1, 2.5) + rect(10, 6.5, 9, 4.5, "#5d6b80", DARK, 1.0, 1) + circle(16, 18.5, 6, "#dfe9f8", DARK, 1.1) + circle(16, 18.5, 3, BLUE, "#1d4f9e", 0.8) + circle(25, 13.5, 1.2, GOLD, GOLD, 0.5),
    "TABLES_BOM": GRID + "".join(balloon(7, 13.5 + 5 * i, str(i + 1), 2.2) for i in range(3)) + "".join(line(14, 13.5 + 5 * i, 24, 13.5 + 5 * i, "#8a9ab0", 1) for i in range(3)),
    "TABLES_GENERAL_TOLERANCE": GRID + rect(13, 15, 18, 14, "#ffffff", BLUE, 1.2, 2) + text(22, 26.5, "&#177;", BLUE, 13),
})
os.makedirs(OUT, exist_ok=True)
for k, body in ICONS.items():
    open(os.path.join(OUT, k + ".svg"), "w").write(svg(body))
print(len(ICONS))
