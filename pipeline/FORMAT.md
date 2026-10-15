# Grid recordings: converting a public dataset for the viewer

Each public dataset gets two files in `pipeline/converters/` (the viewer working tree `~/src/human-mcap-viewer` sees
this directory as `ext/` through a symlink):

- `<name>.py` converts one episode of the original release into `site/data/<prefix><episode>.json` plus a small poster
  `site/media/<prefix><episode>.jpg` (240 px wide JPEG). `egotouch.py` is the simplest reference; `trex.py` shows
  partial fetches (parquet row groups, video slices), force vectors and a tactile-image mosaic.
- `<name>.meta.json` describes the collection for the left rail and header (see `egotouch.meta.json`): `id`, `prefix`,
  `order`, `group: "public"`, `title`, `provider`, `kind: "recording"`, `status {label, tone: ok|warn|neutral}`, `about`,
  `link {label, href}`, `sensor {type: "coverage", coverage: [tip|phalanx|palm], taxels}`, `hardware [{k, v, d}]` (2–4 rows),
  `notes`. Only state what the release or paper says; if something is unknown, say so.

In `~/src/human-mcap-viewer`, `python3 make_manifest.py --site site --originflow ~/data/originflow --local` lists the converted episodes with local media, so
`python3 -m http.server` in `site/` (or a range-capable server) shows them before anything is uploaded.

## Episode JSON (`kind: "grid"`)

```
{
  "id": "<prefix><episode>", "kind": "grid", "title": "<task, sentence case>",
  "n": <frames>, "fps": <clock rate>, "duration": n / fps,
  "videos": [ {"key", "title", "src", "src_size": [w, h], "fps_src", "wide"?: true} ],  // first one is drawn large;
                                                                            // "wide" spans the row (e.g. a tactile mosaic)
  "hands":  [ {"key": "lh"|"rh", "title", "rate", "rows", "cols",
               "cells": b64 Uint16 (row*cols + col of every taxel, in storage order),
               "tax":   b64 Uint8, n x len(cells), 255 = "range",
               "range": <value of 255 in "unit">, "unit": "raw counts" | "N" | ...,
               "regions": [ {"name": "thumb"|"index"|"middle"|"ring"|"little"|"palm"|..., "cells": [indices into cells]} ],
               "label"?: "5 fingertip sensors · 10×10 cells each",  // card header; default "<n> taxels"
               "index"?: b64 Uint16 (n),   // row of "tax" shown at each clock tick, for a panel stored at fewer rows than the
                                           // clock (e.g. a 101-step processed map); "tax" then has max(index)+1 rows. Default: row = tick
                                           // "rate" may be null for such a panel (the header then shows no Hz)
               "paint"?: b64 Uint16 (rows*cols),  // taxel index + 1 (into "cells") drawn in every grid cell, 0 = empty: lets
                                           // a taxel fill the area of its pad; cells touch and borders between taxels are cut out.
                                           // "cells" still holds one cell per taxel (used for vectors). Default: one square per taxel
               "inactive"?: [row*cols + col, ...],  // grid positions of taxels the hand has but the release does not contain
                                           // (lost or never recorded): drawn as hollow squares so the sensor footprint stays visible
               "vectors"?: {"label": "fingertip force", "unit": "N", "range": <value drawn as a full block>,
                            "axes": "(Fx, Fy)", "zname": "Fz",
                            "items": [ {"region": "<region name>", "data": b64 Float32 n x 3} ]} } ],
                            // drawn at the region's centre: arrow = (x, y) with x right and y up, ring = |z| (dashed if z < 0)
                            // an item may give "cells": [indices into cells] instead of "region", to draw one vector per
                            // sensor pad inside a larger region (e.g. per XELA pad on a finger; see tdex.py)
  "series": [ {"title", "lines": [ {"name", "data": b64 Float32 (n), "col"?, "dash"?} ], "fixed"?: [lo, hi], "legendText"?} ],
  "notes":  "<p>HTML: how streams were aligned, what the values mean, what was left out</p>",
  "task":   {"task": "<name>", "start": s, "end": s, "steps": [ {"start": s, "end": s, "text": "..."} ]},   // optional: annotated phases,
                                                                                                  // drawn as a band under the scrub bar
  "item":   {"id", "title", "label", "sub", "poster": "media/<id>.jpg"}  // the rail entry
}
```

- One clock: every array has `n` rows on a common time base starting at t = 0 (the first video frame, if there is video).
  Resample tactile to that clock (latest sample at or before each tick) and say in `notes` what the native rates are.
- `rows x cols` is a 2-D layout of the hand: put each taxel where it sits on the hand (fingers on top, palm below). Use the
  release's own layout if it has one; otherwise build one from the paper's figure and say so in `notes`. Robot hands use the
  same idea (one block per finger pad / sensor).
- Regions are ordered thumb, index, middle, ring, little, then anything else (palm, ...). The viewer colours the first five
  like the other collections and plots per-region sums. When a hand's regions use finger names, colours follow the name
  (so a three-finger hand with thumb, index, middle, palm keeps the finger colours and a muted palm); otherwise they
  follow the position.
- Quantise to uint8 against a fixed `range` (e.g. the sensor's full scale or the episode's 99.5th percentile); never per frame.
- Videos: if the original files are on Hugging Face and playable in a browser (H.264/AV1/VP9 in mp4/webm), point `src` at
  `https://huggingface.co/datasets/<repo>/resolve/<commit sha>/<path>` instead of copying them. Otherwise transcode to H.264
  mp4 (`-c:v libx264 -crf 28 -preset veryfast -pix_fmt yuv420p -movflags +faststart`, at most 960 px wide) into
  `site/media/<id>_<key>.mp4` and use a relative `src` — but only if the dataset license allows redistribution.
- **Every tactile and force channel of the release is shown** (see the channel list in the survey):
  - Taxel arrays go into `hands` (cells).
  - 3-axis forces and wrenches go into `vectors` on the matching region, plus `series` plots of the components or the
    normal/tangential split and the moment magnitude.
  - Scalar pressure/force per sensor becomes one cell per sensor, or a `series`.
  - Camera-based tactile images (raw or deformation) become a mosaic video (`wide`), in addition to any pooled grid.
  - Contact flags become a `series` or `task` steps.
  - Anything left out is named in `notes` with the reason (corrupted, undocumented, too large).
  - Non-tactile streams (joints, actions, depth, IMU) are optional, but `notes` says which ones are not shown.
- Touch-only releases: `"videos": []` is allowed. The viewer then drops the video column and lays the hand panels side by
  side across the full width (one column on a phone). The rail poster is then a picture of the taxel grid (see
  `opentouch.tactile_poster`, `adl21.poster`).
- Processed maps stored on a different timeline than the raw stream (resampled, time-normalized, warped) can be shown as a
  second panel with `"index"` mapping each clock tick to the stored row; say in `notes` how that mapping was obtained.
- Gloves whose taxels are pads of different size and shape (drawn in the paper as a hand outline) can use `"paint"` to fill
  each pad's area on a finer grid instead of one square per taxel; say in `notes` where the pad outlines come from
  (see `reachgrasp.pad_map`).
- Sensors that the release records only partly (e.g. a corrupted or shifted array that keeps some readings) list the
  missing taxels in `"inactive"`, so the panel shows the full sensor footprint with the recorded taxels filled; say in
  `notes` why the others are missing (see `humanoid_everyday.py`). Taxels that are recorded but faulty (e.g. toggling
  between rest and full scale with quiet neighbours) can be left out of `cells` and listed in `"inactive"` the same way,
  with the detection rule and the cells named in `notes` (see `actionsense.faulty_cells`).
- Keep each episode JSON under ~2 MB (shorten to a representative 20–60 s window if needed and say so).
