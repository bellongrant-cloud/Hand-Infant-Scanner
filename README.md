# Hand Infant Scanner — Dermatoglyphic Ridge Count

Computes a **Galton-style ridge count** (the standard dermatoglyphic
measurement used in palm/finger print research and genetic screening)
from a scanner image: the number of ridges crossed by a straight line
drawn between a **delta** (triradius) and a **core** (pattern center).

## How it works

1. **Preprocessing** (`preprocessing.py`) — load the scan, normalize
   brightness/contrast, and segment the skin/ridge area from blank
   background.
2. **Orientation & frequency fields** (`orientation.py`) — estimate local
   ridge direction and spacing per block (gradient method with
   doubled-angle smoothing, x-signature frequency estimate).
3. **Ridge enhancement** — a Gabor filter bank tuned to each block's local
   orientation/frequency sharpens ridges and suppresses noise.
4. **Binarization & skeletonization** — Otsu threshold, then thin to
   1px-wide ridge lines.
5. **Singular point detection** (`singular_points.py`) — Poincaré index
   over the orientation field proposes core/delta candidates. This step
   is a *best-effort assist*: on noisy, partial, or low-contrast infant
   scans it can misfire, so **you can always override it** with manually
   marked coordinates (recommended for anything you need to trust).
6. **Ridge counting** (`ridge_count.py`) — walks the line from delta to
   core over the skeleton, counting distinct ridge crossings (small
   skeleton gaps are bridged so one ridge isn't double-counted).
7. **Visualization** (`visualize.py`) — writes an annotated image showing
   the skeleton, the core/delta points, the counting line, and every
   counted crossing, so a human can verify the count at a glance.

## Usage

Three ways to run this, from most to least hands-on:

- `ridge_count_gui.py` — a point-and-click window: open an image, click to
  mark the core/delta points on the picture itself, click "Count Ridges".
  No typing, no coordinates. **Needs `ridge_count_standalone.py` in the
  same folder** (it reuses that file's logic).
- `run_ridge_count.bat` / `ridge_count_standalone.py` — drag-and-drop, or
  command line, auto-detecting core/delta.
- `ridge_scanner/` — the same logic as the modular package, for
  integrating into another project.

All of them only need `numpy` and `opencv-python-headless` (no
scikit-image, no C compiler, no Visual Studio Build Tools).

### Option A — Windows, point-and-click GUI (easiest, most accurate)

1. Download `ridge_count_gui.py` and `ridge_count_standalone.py` (and
   optionally `Ridge Count GUI.bat`) into the same folder.
2. Open Command Prompt once and run:
   ```
   pip install numpy opencv-python-headless
   ```
3. Double-click **`Ridge Count GUI.bat`** (or run
   `python ridge_count_gui.py`). In the window:
   - **Open Scan Image…**
   - Click **Mark Core**, then click the core point on the picture.
     Click **Mark Delta**, then click the delta point.
   - Click **Count Ridges** — the count appears, and the picture updates
     to show exactly which ridges were counted (green dots) so you can
     verify it at a glance.
   - **Save Results…** to write the annotated image + a JSON report.

### Option B — Windows, drag-and-drop (no marking, auto-detect only)

1. Download `ridge_count_standalone.py` and `run_ridge_count.bat` into
   the same folder.
2. `pip install numpy opencv-python-headless` (once).
3. Drag a scan image onto `run_ridge_count.bat`. It runs the tool, writes
   results next to your image in a `ridge_count_out` folder, and opens
   that folder. Core/delta are auto-detected — check `annotated.png`,
   since auto-detection can misfire (use Option A if it does).

### Option C — command line (any OS, full control)

```bash
pip install -r requirements.txt

# Auto-detect core/delta (verify the warnings + annotated image!)
python ridge_count_standalone.py path/to/scan.png --output-dir out/

# Manually specify core/delta (recommended for accuracy)
python ridge_count_standalone.py path/to/scan.png --core 128,85 --delta 128,200 --output-dir out/

# The modular package works the same way:
python -m ridge_scanner.cli path/to/scan.png --output-dir out/
```

This writes `out/annotated.png` (visual proof of the count) and
`out/report.json` (machine-readable result). Pass `--json` to also print
the report to stdout.

### Key options

| Flag | Meaning |
|---|---|
| `--core X,Y` / `--delta X,Y` | Manually mark the singular points instead of relying on auto-detection. |
| `--block-size` | Orientation-field block size in px (default 16). Smaller = finer but noisier. |
| `--band-half-width` | Perpendicular tolerance (px) when sampling the skeleton along the line (default 1). |
| `--exclude-px` | Ignore this many px at each line endpoint, to avoid counting the ridge the core/delta point itself sits on. |

## Accuracy notes / limitations

- **Automatic core/delta detection is the weakest link.** The Poincaré
  index method is standard but sensitive to image quality, especially on
  infant palm prints where skin is soft, prints can smudge, and patterns
  are still small. Always check `out/annotated.png` before trusting an
  auto-detected count, and prefer manually marked points for anything
  used in a real assessment.
- The ridge-counting step itself (given correct core/delta points) is
  the accuracy-critical, well-tested part of this tool — see
  `tests/test_ridge_count.py` for exact-count verification against
  synthetic ridge patterns at multiple spacings and angles.
- This tool is a research aid, not a certified clinical diagnostic
  instrument.

## Tests

```bash
python -m pytest tests/ -v
```

`tests/test_ridge_count.py` validates the counting algorithm against
synthetic ridge patterns with known, exact ridge counts (multiple
spacings, horizontal/diagonal lines, endpoint exclusion, skeleton-gap
bridging). `tests/test_pipeline_integration.py` runs the full pipeline
end-to-end on a synthetic fingerprint-like image. `tests/test_gui_logic.py`
drives the GUI (simulated clicks → count → save) and is skipped
automatically if Tkinter or a display isn't available.
