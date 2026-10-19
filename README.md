# Hand Infant Scanner: Ridge Counter

Counts the ridges between two points on a fingerprint or palm scan. This is the
classic dermatoglyphic ridge count (Galton–Henry method): the number of ridges
crossed by a straight line from the **delta** (triradius) to the **core**. It
also works for palm counts such as the **a–b ridge count**: put the two points
on triradii a and b.

![Ridge Counter window](docs/screenshot.png)

## Quick start (Windows)

1. **Python.** If `python` works in a terminal, you already have it. Otherwise
   install it from [python.org](https://www.python.org/downloads/) and tick
   *Add python.exe to PATH*.
2. **Download this project.** Click the green **Code** button, then
   **Download ZIP**, and unzip it anywhere (for example, Documents).
3. **Double-click `Ridge Counter.bat`.** The first time, it offers to install
   two free add-ons (numpy and OpenCV). Click **Install** and wait a minute.
   You don't need PowerShell.
4. **Open your scan**, or drag the scan file onto `Ridge Counter.bat`.

## Using the window

| To… | Do this |
|---|---|
| Place the core or delta | Choose *Core* or *Delta* next to "Click places", then left-click the image. After you place the core, the next click places the delta. |
| Move a point | Drag it. The count updates as you move it. |
| Zoom and pan | Use the mouse wheel to zoom and right-drag (or middle-drag) to pan. **F** fits the scan to the window. |
| Check the count | Green numbered dots are the counted ridges. Grey rings are ridges the core or delta sits on, which by convention are not counted. |
| Start over | Click *Clear points*, or *Auto-detect* to bring back the automatic suggestions. |
| Save | *Save results…* writes `<scan>_ridgecount.png` (annotated picture) and `<scan>_ridgecount.json`, and adds a row to `ridge_counts.csv` in the folder you choose. You get one row per saved count, ready for Excel. |

Keyboard: Ctrl+O to open, Ctrl+S to save, C or D to choose core or delta,
+ or − to zoom, F to fit.

## Child records, Down syndrome markers and the model (research use)

The **Child record** and **Model** tabs collect everything the
dermatoglyphics literature links to Down syndrome. A child's record holds:

- **Each fingertip:** the pattern (arch, ulnar loop, radial loop or whorl)
  and its ridge count.
- **Each palm:** the ATD angle, the a–b ridge count and the crease type
  (normal, Sydney line, or single transverse "simian" crease).
- **Each sole:** whether the big-toe area has a tibial arch.

**Filling in a record**

1. On the *Ridge count* tab, measure a finger (core and delta), then click
   *Add to child record…*. Pick the hand and finger. The pattern is suggested
   from the cores and deltas found; please check it. The ridge count is
   filled in for you.
2. For a palm, switch *Measure* to *Palm*. Click triradii **a**, **b**,
   **d** and the axial triradius **t**. The window shows the a–b ridge
   count, the ATD angle and the t / t′ / t″ position. Then click *Add to
   child record…* and choose the crease type by eye.
3. On the *Child record* tab, give the child an ID and the chromosome test
   result (if known), fill in anything else by hand, and click **Save**.

**What you get**

- **A marker report** for every record. It lists each marker, what this
  child shows, what the papers report in Down syndrome, and the source.
  Only markers that are distinctive on their own are flagged: a distal
  axial triradius (ATD angle above 56°, which can over-flag newborns), a
  single transverse crease, a Sydney line, and a tibial arch on the sole.
  Finger patterns and ridge counts are shown but not flagged. The reviews
  give no cut-off for them, and these patterns are common in children
  without Down syndrome.
- **A trainable model** (Model tab). It learns only from records whose
  chromosome test result is known. It refuses to train until there are at
  least 20 children with Down syndrome and 20 without. When it does train,
  it reports accuracy measured on children it wasn't trained on: how many
  it caught, how many it wrongly flagged, with 95% ranges. Today there are
  no Down syndrome records, so there is no trained model, and the window
  says so instead of showing a made-up probability.

Records are saved as files in `Documents\Ridge Counter Data` on your own
computer and are never uploaded. *Export spreadsheet…* writes everything
to one CSV. **Never commit real children's records or scans to this public
repository.**

**This is a research aid, not a diagnosis.** Many children without Down
syndrome show some of these markers, and some children with Down syndrome
show none. Down syndrome is confirmed with a chromosome test (karyotype).
Prints from newborns need high resolution: their ridges are 2.5–3 times
finer than adults', and published newborn studies used roughly
1500–3600 dpi.

## Getting an accurate count

- **Scan resolution.** Infant ridges are fine (about 0.3–0.4 mm apart), so scan
  at **1000 dpi or more** if you can. 500 dpi is the minimum, with ridges about
  6 px apart. After you open a scan, the status bar shows the measured ridge
  spacing. Below about 5 px, the scan is too coarse to count reliably.
- **Check the points.** Auto-detected points, labelled *(auto)*, are only a
  starting suggestion. Zoom in and drag them to the exact places: the core on
  the innermost recurving ridge, and the delta at the centre of the triradius.
- **The endpoint rule.** A ridge isn't counted if the core or delta sits on it.
  Whether a point counts as "on" a ridge can change the total by one, so zoom in
  when you place points and check the grey rings.
- **The delta has to be in the print.** Flat (un-rolled) prints often stop
  short of the deltas at the lower corners of the fingertip. Without a
  delta, there's no ridge count. Roll the finger from nail edge to nail edge
  if you can. A whorl has two deltas; count each side separately.
- **Whole-hand scans.** Auto-detect pairs each delta with the nearest core
  on the same finger. To count a particular finger, click its core and then
  press *Auto-detect*. It keeps your point and finds that finger's delta.
- **Light ridges.** If your scanner shows ridges as light lines on a dark
  background, tick *Light ridges*.
- **Blue overlay.** The blue tint shows exactly what the program treated as
  ridge. Where it disagrees with what you can see (smudges, creases, scars),
  trust your eyes and adjust the count.

## Command line (optional)

```
python ridge_counter.py count scan.png                                 # auto-detect core and delta
python ridge_counter.py count scan.png --core 512,388 --delta 301,690
python ridge_counter.py count scan.png --output-dir results --json
```

Options:

- `--light-ridges`
- `--ridge-period PX` overrides the measured ridge spacing.
- `--output-dir DIR` writes the same files as *Save results*.
- `--json`

Run `python ridge_counter.py count --help` for details. To install the add-ons
yourself: `python -m pip install -r requirements.txt`.

## How it works

1. Evens out uneven brightness and contrast across the scan.
2. Measures the ridge spacing from the image's frequency spectrum, so it adapts
   to any scanner resolution.
3. Estimates the ridge direction at every pixel, then sharpens the ridges with
   Gabor filters tuned to that direction and spacing.
4. Separates the print from the background by how ridge-like each area is.
5. Finds cores and deltas from the Poincaré index of the ridge-direction field.
6. Walks the line from the delta to the core and counts the ridges it crosses.
   It bridges pores and small breaks, ignores specks, and leaves out the ridges
   under the two points.

## Accuracy

These figures come from synthetic scans where the right answer is known. The
scans had noise, blur and uneven lighting, with ridge spacings from 5 to 18 px.

- **Straight and circular ridge patterns:** exact on every test line, for
  both dark and light ridges.
- **Realistic loop prints** (with ridge endings, forks, a core and a delta),
  compared with what is visible in the image:
  - About 89% of lines between hand-picked points were exact, and over 99%
    were within one ridge.
  - The core-to-delta line was exact in about 72% of prints and within one
    ridge in 97%.
  - Cores and deltas were found within one ridge-width of their true position.

Errors happen where a ridge ends or forks right on the line, and where a
point sits on the edge of a ridge. That's why the window shows every counted
ridge: have a person confirm any count that matters. This is a research aid,
not a certified clinical device.

## For developers

```
python -m pip install -r requirements-dev.txt
python -m pytest
```

The code is in two files: `ridge_counter.py` (image analysis, counting,
window and command line) and `dermatoglyphics.py` (child records, the marker
report and the model). Keep both in the same folder.

The model tests in `tests/test_dermatoglyphics.py` use made-up labelled
records only to check that training and evaluation work: that the model
refuses too little data, learns a real difference, and doesn't look accurate
on noise. They say nothing about real children.

`tests/synthetic.py` generates the synthetic prints. Run
`python -m tests.synthetic` to regenerate `sample_data/sample_loop.png`. The
GUI tests run when Tkinter and a display are available, and are skipped
otherwise.
