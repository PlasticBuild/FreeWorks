"""The plate's own look per printer and plate type (our own drawings, no slicer artwork): the rim round the bed,
the printer's name and size on the front rim, the origin axes, the build volume's faint edges, and the plate
finish (smooth or textured) for the chosen plate type."""
import math

RIM_COLOUR = (0.13, 0.14, 0.16)
LABEL_COLOUR = (0.78, 0.80, 0.84)
VOLUME_COLOUR = (0.34, 0.36, 0.40)

# plate type -> (colour, grain). Grain: "diamond" textured PEI, "dots" supertack, None smooth
FINISH = {
    "Cool Plate": ((0.27, 0.30, 0.34), None),
    "Engineering Plate": ((0.32, 0.30, 0.28), None),
    "High Temp Plate": ((0.21, 0.22, 0.24), None),
    "Textured PEI Plate": ((0.24, 0.25, 0.27), "diamond"),
    "Supertack Plate": ((0.26, 0.31, 0.37), "dots"),
}


def finish(plate_type):
    return FINISH.get(plate_type) or FINISH["Textured PEI Plate"]


def grain_image(kind):
    """(size, bytes) of a one-channel tile for the face, or None for a smooth plate. Repeats every 6 mm."""
    if kind is None:
        return None
    n = 16
    grain = bytearray()
    for j in range(n):
        for i in range(n):
            if kind == "diamond":
                d = ((i + j) % 4 == 0) + ((i - j) % 4 == 0)
                grain.append(255 - 34 * d - 9 * ((i * 7 + j * 3) % 5 == 0))
            else:
                grain.append(255 - 26 * ((i % 4 == 1) and (j % 4 == 1)) - 8 * ((i * 5 + j * 11) % 7 == 0))
    return n, bytes(grain)


def rim_points(bed, width=7.0):
    """The bed outline pushed out by width mm."""
    xs = [p[0] for p in bed]
    ys = [p[1] for p in bed]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if len(bed) == 4 and all(abs(p[0] - x0) < 1e-6 or abs(p[0] - x1) < 1e-6 for p in bed) \
            and all(abs(p[1] - y0) < 1e-6 or abs(p[1] - y1) < 1e-6 for p in bed):
        return [(x0 - width, y0 - width), (x1 + width, y0 - width), (x1 + width, y1 + width), (x0 - width, y1 + width)]
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    out = []
    for x, y in bed:
        d = math.hypot(x - cx, y - cy) or 1.0
        out.append((x + (x - cx) / d * width, y + (y - cy) / d * width))
    return out


def art_node(bed, height, name, over=False):
    """Coin node. over=False: the rim, drawn before the plate face; over=True: build volume, origin axes and the front
    label, drawn after it. bed: [(x, y)], height: mm, name: printer name."""
    from pivy import coin
    root = coin.SoSeparator()
    xs = [p[0] for p in bed]
    ys = [p[1] for p in bed]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    # rim: a flat face just under the plate
    rim = coin.SoSeparator()
    rim.addChild(coin.SoTexture2())
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    rim.addChild(light)
    m = coin.SoMaterial()
    m.diffuseColor = RIM_COLOUR
    rim.addChild(m)
    pts = [(x, y, -0.2) for x, y in rim_points(bed)]
    c = coin.SoCoordinate3()
    c.point.setValues(0, len(pts), pts)
    rim.addChild(c)
    f = coin.SoFaceSet()
    f.numVertices.setValue(len(pts))
    rim.addChild(f)
    if not over:
        root.addChild(rim)
        return root
    # build volume: faint dashed top outline and four uprights
    vol = coin.SoSeparator()
    vol.addChild(coin.SoTexture2())
    vol.addChild(light)
    vm = coin.SoMaterial()
    vm.diffuseColor = VOLUME_COLOUR
    vol.addChild(vm)
    ds = coin.SoDrawStyle()
    ds.lineWidth = 1.0
    ds.linePattern = 0xF0F0
    vol.addChild(ds)
    top = [(x, y, height) for x, y in bed] + [(bed[0][0], bed[0][1], height)]
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)] if len(bed) == 4 else \
        [(x0, (y0 + y1) / 2.0), (x1, (y0 + y1) / 2.0), ((x0 + x1) / 2.0, y0), ((x0 + x1) / 2.0, y1)]
    ups = []
    for x, y in corners:
        ups += [(x, y, 0.0), (x, y, height)]
    vc = coin.SoCoordinate3()
    vc.point.setValues(0, len(top) + len(ups), top + ups)
    vol.addChild(vc)
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, 1 + len(ups) // 2, [len(top)] + [2] * (len(ups) // 2))
    vol.addChild(ls)
    root.addChild(vol)
    # origin axes, where the printer's origin lies on the bed
    if x0 - 1.0 <= 0.0 <= x1 + 1.0 and y0 - 1.0 <= 0.0 <= y1 + 1.0:
        ax = coin.SoSeparator()
        ax.addChild(coin.SoTexture2())
        ax.addChild(light)
        st = coin.SoDrawStyle()
        st.lineWidth = 3.0
        ax.addChild(st)
        for colour, end in (((0.90, 0.25, 0.25), (28.0, 0.0, 0.0)), ((0.30, 0.78, 0.35), (0.0, 28.0, 0.0)),
                            ((0.30, 0.50, 0.95), (0.0, 0.0, 28.0))):
            one = coin.SoSeparator()
            mm = coin.SoMaterial()
            mm.diffuseColor = colour
            one.addChild(mm)
            pc = coin.SoCoordinate3()
            pc.point.setValues(0, 2, [(0.0, 0.0, 0.02), (end[0], end[1], max(0.02, end[2]))])
            one.addChild(pc)
            l2 = coin.SoLineSet()
            l2.numVertices.setValue(2)
            one.addChild(l2)
            ax.addChild(one)
        root.addChild(ax)
    # the name and the size, lettered flat on the front rim
    label = coin.SoSeparator()
    label.addChild(coin.SoTexture2())
    lm = coin.SoMaterial()
    lm.diffuseColor = LABEL_COLOUR
    label.addChild(lm)
    tr = coin.SoTranslation()
    tr.translation = ((x0 + x1) / 2.0, y0 - 5.6, 0.05)
    label.addChild(tr)
    font = coin.SoFont()
    font.size = 4.0
    label.addChild(font)
    text = coin.SoText3()
    text.justification = coin.SoText3.CENTER
    size = "%g x %g x %g mm" % (round(x1 - x0, 1), round(y1 - y0, 1), round(height, 1))
    text.string = "%s    %s" % (name or "", size)
    label.addChild(text)
    root.addChild(label)
    return root
