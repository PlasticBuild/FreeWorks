# FreeWorks — FreeCAD add-on

[![Donate on Ko-fi](https://img.shields.io/badge/Donate-Ko--fi-FF5E5B?style=for-the-badge)](https://ko-fi.com/plasticbuild)

**0.4.0-alpha · FreeCAD 1.1.4 · Windows**

**Like the SOLIDWORKS interface and want to work in FreeCAD?** FreeWorks brings a familiar commercial-CAD workflow to stock FreeCAD 1.1.4, from the first sketch through parts, assemblies, and drawings.

FreeWorks is an independent add-on for FreeCAD. Install it into your existing FreeCAD setup. The application still appears as **FreeCAD**.

[**Download FreeWorks 0.4.0-alpha**](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.4.0-alpha)

See the [0.4.0-alpha release notes](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.4.0-alpha) for what is new and for known issues.

The alpha icons come in light and dark sets. See [Icons](#icons).

[Download the six-column icon comparison PDF](https://raw.githubusercontent.com/PlasticBuild/FreeWorks/main/docs/FreeWorks-Icon-Comparison.pdf)

## What you can try

| Area | Workflow |
| --- | --- |
| Interface | Find commands on ribbon-style tabs, edit feature settings in task panels, and step through the model with the feature tree and rollback bar. Light and dark themes are available. |
| Sketching | Snap to endpoints, midpoints, and centres. Use inference lines and automatic relations as you draw, then set sizes with Smart Dimension. |
| Part modelling | Turn sketches into parts with extrudes, revolves, sweeps, and lofts. Refine them with fillets, holes, patterns, and mirrors. |
| Assemblies | Insert components and position them with mates. Check for interference or create an exploded view. |
| Drawings | Create projected, section, and detail views, add dimensions and annotations, and export to PDF or DXF. |

Sketching is the best place to start. The walkthrough below takes you from a snapped rectangle to an extruded part. This is an early alpha, so expect rough edges and verify results before relying on them.

## Screenshots

![FreeWorks part workspace showing the bearing mount, ribbon, feature tree, and rollback bar](docs/images/freeworks-part-alpha1.png)

![FreeWorks sketch editor showing the shaded bearing mount profile](docs/images/freeworks-sketch-alpha1.png)

## Requirements and quick install

- Use stock FreeCAD **1.1.4**. Windows has been tested. Other operating systems are untested.
- Install with FreeCAD's **Addon Manager** from this repository's URL, download **FreeWorks-0.4.0-alpha.zip** from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.4.0-alpha), run the optional Windows installer from the same release, or install from source. The [installation guide](docs/INSTALL.md) covers each way.

Orca, Bambu, PrusaSlicer, and Diotopo are optional in-app downloads. Each is downloaded separately. The add-on package excludes all four.

## Icons

The add-on ships its alpha icon set in `swstyle/resources/icons`: a light set (`png/`, `fc/`) and a dark set (`dark/`). It picks the set that matches FreeCAD's theme. These icons were made with AI tools for this alpha and are styled after the commercial-CAD look this add-on follows. A command that has no icon in the set uses the add-on's drawn icon (`swstyle/resources/icons-drawn`), then FreeCAD's own icon, then a tile with its initials.

The package also includes the ANSI and ISO drawing sheet formats (`swstyle/sheetformats`), the 3D Slicer tab pictures, which were drawn for this add-on (`swstyle/resources/slicer`), and the environment pictures (`swstyle/resources/environments`). The environment pictures are made from Poly Haven CC0 HDRIs; see the LICENSE.txt in that folder. The tip pictures are not included yet.

To use icons of your own instead, set the `IconRoot` preference (Tools > Edit parameters > Preferences/Mod/FreeWorks) or the `SWSTYLE_ICONS` environment variable to a folder with the same layout, and restart FreeCAD.

## Repository layout

The add-on source lives at the root of this repository. The repository root is the add-on folder, so it installs as `Mod/FreeWorks` with no extra steps.

| Path | What it holds |
| --- | --- |
| `Init.py`, `InitGui.py` | Start-up files that FreeCAD runs. `InitGui.py` applies the interface. |
| `package.xml` | Add-on metadata for the Addon Manager: name, version, licence, and icon. |
| `swstyle/` | The interface, sketch tools, features, assemblies, drawings, and their resources. |
| `smcore/` | The bundled SheetMetal engine, unmodified (LGPL, see `THIRD-PARTY.md`). |
| `swfiles/` | File import and export helpers. |
| `icons/` | The add-on's own icon. |
| `docs/` | Install, feedback, and alpha guides, plus the screenshots on this page. |
| `.github/workflows/release.yml` | Builds the release zip from the tagged source. |

Releases are only for tagged builds. Pushing a tag such as `v0.4.1-alpha` builds `FreeWorks-0.4.1-alpha.zip` with `git archive` from that tag, so the zip always matches the committed source. The tag must match the version in `package.xml`.

## Install from source

1. Find your user `Mod` folder. In FreeCAD's Python console, enter `App.getUserAppDataDir()`. The `Mod` folder sits inside that path. On a new FreeCAD 1.1 profile it is `%APPDATA%\FreeCAD\v1-1\Mod` on Windows and `~/.local/share/FreeCAD/v1-1/Mod` on Linux. A profile carried over from an older FreeCAD can still use `%APPDATA%\FreeCAD\Mod`.
2. Close FreeCAD. Then clone the repository into that folder as `FreeWorks`, for example on Windows:
   `git clone https://github.com/PlasticBuild/FreeWorks.git "%APPDATA%\FreeCAD\v1-1\Mod\FreeWorks"`
3. Check that `InitGui.py` sits directly inside `Mod/FreeWorks`, then start FreeCAD.
4. To update later, close FreeCAD, run `git pull` in that folder, and start FreeCAD again.

Without git, use **Code > Download ZIP** on this page, extract it, and rename the `FreeWorks-main` folder to `FreeWorks` before you move it into `Mod`.

## First 15 minutes

1. Open a new part, select a plane, and open a sketch.
2. Draw a rectangle. Start a line near a corner or the midpoint of an edge and watch the snap cue. Move the pointer horizontally or vertically to see the inference line and relation appear as you draw.
3. Remove the practice line so the rectangle is the only profile. Use Smart Dimension on two adjacent edges and enter their lengths in the Modify box.
4. Exit the sketch, select the rectangle sketch, and use Extrude. Enter a depth and accept the preview.

## Status · 0.3.0-alpha1

These notes cover 0.3.0-alpha1. Everyone is welcome to report bugs, suggest features, or share feedback in [GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues). See the [feedback guide](docs/FEEDBACK.md) for what to include.

### Known problems

- **Parting Surface.** The Sharp and Smooth corner options leave corners unfilled.
- **Dimension Text.** Inspection, Justify, Offset, and the second text line are unavailable. Add Parentheses works.
- A Distance-Distance chamfer that meets a Vertex chamfer corner can fail to build.
- Some files may freeze when rebuilding complex surfaces after an edit or during certain drawing steps. Save often.
- Some drawings may reopen blank. If that happens, try rebuilding with **Ctrl+Q**.
- Some panel wording and layouts may differ from the intended workflow.

### Shortcomings

- FreeWorks runs on stock FreeCAD 1.1.4 and inherits limits from its geometry kernel and assembly solver.
- Sheet metal, weldments, and mold tools have had less testing than parts, assemblies, and drawings.
- Drawing flat patterns, weldment cut-list tables, and the Sketch Blocks and Library Feature panels are still pending.

### Actively being worked on (coming in the next version)

- **Sketching:** smarter snapping and inference lines, and more automatic relations while you draw.
- **Features:** Thin cut from an open line, Full Round on slot ends, and more fillet and chamfer options on surfaces.
- **Sheet metal and weldments:** a full pass on flanges, hems, fold and unfold, structural members and cut lists.
- **Mold tools:** Parting Surface corner options and the rest of the mold panels.
- **Drawings:** flat pattern views, weldment cut-list tables, and Dimension Text options (Inspection, Justify, Offset, second text line).
- **Assemblies:** more mate types, Motion Study polish, and Make Independent.
- **Interface:** panel-by-panel layout and wording polish, Sketch Blocks, and Library Features.
- **Stability:** fixes from automated tutorial walk-throughs and from tester reports.

## Guides

- [Install, update, or remove FreeWorks](docs/INSTALL.md)
- [Give feedback](docs/FEEDBACK.md)
- [Alpha status, known problems, and planned work](STATUS.md)
