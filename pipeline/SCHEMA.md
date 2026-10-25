# Survey file: `pipeline/surveys/<id>.json`

One file per dataset, written by step 1 (survey), extended by step 2 (sample plan) and step 3 (visualization). It is the
record of what was checked and decided; `entry` is what goes into `data/datasets.json` (`pipeline/merge_entry.py`).

Only fill a field from a primary source (paper, supplementary, project page, dataset card/README, code repository, the
files themselves). Unknown -> `null` (never guess). Numbers are numbers, not strings. Text is short, factual, English.

```
{
  "id": "humanoid_everyday",            // lowercase, [a-z0-9_]; catalog id
  "surveyed": "2026-10-15",
  "entry": { ... },                      // full catalog entry, below
  "license": {
    "name": "Apache-2.0",                // as written by the authors, or "not stated"
    "redistribution": "allowed",         // allowed | not_stated | forbidden  (forbidden only if the text says so)
    "quote": "...",                      // the exact sentence that decides it, if any
    "url": "https://..."                 // where that sentence is
  },
  "download": {
    "where": "https://huggingface.co/datasets/...",
    "access": "open",                    // open | login | form | request | none
    "format": "LeRobot v3 parquet + mp4", // container and layout
    "total_size": "1.2 TB",
    "per_episode": "~40 MB",             // what one sample costs to fetch
    "partial_fetch": "HTTP range requests on parquet row groups"   // how to get one episode without the whole release
  },
  "channels": [                          // EVERY stream in one released episode, not only touch
    {"name": "observation.tactile_force", "kind": "wrench", "shape": "(60,)", "rate_hz": 30, "unit": "not stated",
     "frame": "per fingertip sensor, not documented", "note": "(left, right) x (thumb..pinky) x (Fx, Fy, Fz, Mx, My, Mz)"}
    // kind: tactile_grid (taxel array) | tactile_image (camera-based sensor image) | deformation_map | force_vector (3-axis)
    //       | wrench (6-axis) | pressure_scalar (one value per sensor) | contact_flag | camera | depth | hand_pose | body_pose
    //       | object_pose | joint_state | action | imu | emg | audio | eye_tracking | language | other
  ],
  "episode_index": {
    "where": "meta/episodes/... or a file listing",
    "count": 5464,
    "fields": ["task", "object", "scene", "subject", "duration"],   // what each episode is labelled with
    "tasks": ["..."],                   // distinct task names (all of them if < 300, else the label field and a count)
    "scenes": ["..."]
  },
  "sample": { ... },                    // step 2, see README.md
  "visualization": [ ... ]              // step 3: one row per channel, see README.md
}
```

## `entry`: one catalog entry (`data/datasets.json`)

```
{
  "id", "name", "title", "authors": "First Author et al.", "year": 2026, "venue": "arXiv 2606.17055",
  "summary": "one sentence: hand, sensor, what was recorded",
  "embodiment": "human" | "robot" | "both",
  "hand": "Sharpa Wave (22 DoF) x 2 on Dexmate Vega-1",
  "bimanual": true,
  "sensor": {
    "type": "piezoresistive" | "capacitive" | "vision" | "magnetic" | "unspecified" | "estimated",
    "taxels_per_hand": 162,              // null if not stated; "sensors_per_hand": 5 when the hand has a few discrete sensors
    "coverage": ["tip", "phalanx", "palm"],
    "rate_hz": 30,
    "note": "what one sample contains",
    "maker": "Tekscan",                  // or "custom (<lab>)"
    "model": "Grip System 4256E",
    "principle": "piezoresistive" | "capacitive" | "piezoelectric" | "magnetic" | "optical" | "barometric" | "resistive" | "unspecified",
    "range": "0-350 N"
  },
  "modalities": ["hand_pose", "egocentric", "wrist_rgb", "multiview_rgb", "rgb", "depth", "object_pose", "mocap",
                 "robot_action", "language", "emg", "imu", "eye_tracking", "audio", "segmentation"],
  "scale": {
    "hours": 20, "episodes": 1891, "frames": 2100000, "tasks": 208, "objects": 1000, "subjects": 12,   // subjects null for robots
    "scenes": 5, "scene_types": ["home", "office"],
    "text": "~20 h, 1,891 episodes, 208 tasks, 1,000+ objects, 5 scene types"
  },
  "availability": "public" | "gated" | "partial" | "announced" | "unclear" | "not_released",
  "access": "how to get it, one sentence",
  "license": "CC BY 4.0" | "not stated" | ...,
  "caveats": ["short facts a user must know"],
  "links": {"paper": "...", "project": "...", "data": "...", "code": "..."},
  "image": "https://... teaser figure",   // optional
  "setup": {
    "cameras": [{"role": "egocentric" | "wrist" | "third_person" | "robot_head" | "other", "count": 1, "model": "...",
                 "type": "RGB" | "RGB-D" | "stereo" | "fisheye" | "event" | "thermal", "resolution": "1280x720", "fps": 15,
                 "mount": "head" | "chest" | "neck" | "glasses" | "wrist" | "static" | "robot"}],
    "wrist_cameras": 2,
    "depth": false,
    "tracking": [{"target": "fingers" | "wrist" | "body" | "object",
                  "method": "vision_estimate" | "optical_mocap" | "optical_tracker" | "imu" | "magnetic" | "bend_sensor"
                            | "exoskeleton" | "robot_proprioception" | "teleop_glove" | "other",
                  "system": "Rokoko Smartgloves", "note": "..."}],
    "other": ["EMG", "audio"]
  },
  "sources": ["URLs actually read"],
  "unconfirmed": ["anything derived or not confirmed, and how it was derived"],
  "viewer": "<prefix><episode>",         // set after samples are published: the episode the catalog card opens
  "used_by": [{"name": "TouchWorld (arXiv 2607.07287)", "url": "...", "note": "what it used the data for"}],   // optional
  "zh": {                                // optional: Chinese original for Chinese-language releases
    "name": "白虎-VTouch", "title": "...", "maker": "...",
    "en": "official" | "translated",     // translated = no official English; name/title/summary above are ours
    "note": "release page in Chinese only"
  }
}
```

Tracking methods: `vision_estimate` = pose estimated from video afterwards (WiLoR, HaMeR, MediaPipe) or by a VR headset's
cameras; `optical_mocap` = marker-based (Vicon, OptiTrack); `optical_tracker` = Vive lighthouse; `magnetic` = EMF
(Polhemus, Manus Quantum); `bend_sensor` = resistive flex (CyberGlove). Robot datasets: `subjects` null; cameras are the
robot's; tracking is usually `robot_proprioception`, plus how demonstrations were teleoperated as a second entry.

## Model entry (`data/models.json`)

One record per named model that is trained or evaluated on touch recorded across a hand. Scope and the nightly checks
that keep `release` current are in [NIGHTLY.md](NIGHTLY.md). The models listed here fill each dataset's derived
`used_by` (with `note` from `uses`); a dataset's other users (a derived dataset, for example) go in its hand-written
`used_by_other`, same shape as `used_by`.

```
{
  "id": "touchworld",                  // lowercase [a-z0-9_]; may equal a dataset id when it is the same paper
  "name": "TouchWorld", "title": "full paper title", "authors": "First Author et al.", "year": 2026,
  "venue": "arXiv 2607.07287",         // or "CoRL 2026 (arXiv 2607.07287)" once accepted
  "kind": "world_model" | "policy" | "representation" | "estimation" | "generation" | "other",
       // world_model: predicts future touch and/or video; policy: outputs actions using touch; representation: tactile
       // encoder or pretrained features; estimation: touch from other signals, or pose/state from touch; generation: synthesizes touch
  "summary": "one sentence: what goes in, what comes out, on which hand(s)",
  "embodiment": "human" | "robot" | "both",   // whose hands the touch comes from
  "touch": "input" | "output" | "both",
  "uses": [{"id": "egotouch", "role": "pretraining" | "training" | "fine-tuning" | "evaluation", "note": "what it used, with numbers"}],
  "own_data": "10 h of Wuji-hand teleoperation; not released",   // or null; data of its own that is not a catalog entry
  "dataset": "dextacwam",              // or null; the catalog entry of the data released with this model
  "release": {"code": "released" | "announced" | "not_released", "weights": "released" | "announced" | "not_released",
              "note": "the evidence, with where and when it was seen"},
  "license": "MIT" | "not stated",     // of the released code or weights
  "links": {"paper": "...", "project": "...", "code": "...", "weights": "..."},   // only links that exist; "released" needs the link
  "sources": ["URLs actually read"],
  "unconfirmed": ["anything derived or not confirmed, and how"],
  "checked": "2026-10-25"              // the date the release status was last confirmed
}
```
