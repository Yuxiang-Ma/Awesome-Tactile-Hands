# Awesome Tactile Hands [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> **Taxel Atlas**: a curated catalog of public datasets that record touch across the hand during manipulation, from human tactile gloves to dexterous robot hands with tactile skins.

Browse, filter and compare them on the [live catalog](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/), and play recorded samples in the [data viewer](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/viewer/).

**What gets in.** Tactile sensing *on the hand* (glove or robot hand), recorded while the hand manipulates objects, with data that is released or announced. Each entry states which regions are sensed (fingertips, finger segments, palm), how many taxels per hand, what else is recorded in sync, and how to get it. Numbers are as the authors report them; anything we could not confirm from a primary source is marked as not stated.

**What stays out.** Contact estimated from cameras, pressure pads under the hand, or thermal contact maps on objects (PressureVision, EgoPressure, ContactPose, ContactDB); parallel-jaw grippers; tactile hardware papers with no data.

<!-- BEGIN LIST -->
**22** datasets · updated 2026-10-15

## Human tactile gloves

- [EgoTactile](https://egotactile.github.io/) - Full-hand 162-sensor pressure glove with egocentric video of grasps on 63 everyday objects, plus a bare-hand test set. 162 taxels/hand; fingertips, palm; public. ICML 2026 ([paper](https://arxiv.org/abs/2606.09243), [project](https://egotactile.github.io/), [data](https://huggingface.co/datasets/HustleHard/EgoTactile), [code](https://github.com/Russell-Zeng/EgoTactile)).
- [EgoTouch](https://jianyi2004.github.io/TouchAnything-Website/) - Bimanual pressure gloves with Rokoko hand pose, an egocentric camera and two wrist cameras over 208 tasks. 256 taxels/hand; fingertips, finger segments, palm; public. arXiv 2605.13083 ([paper](https://arxiv.org/abs/2605.13083), [project](https://jianyi2004.github.io/TouchAnything-Website/), [data](https://huggingface.co/datasets/zhouzhoujy/EgoTouch), [code](https://github.com/Jianyi2004/TouchAnything)).
- [TactiDex](https://tactidex.github.io/) - Piezoresistive glove over a MANUS mocap glove with OptiTrack object tracking, single-hand and bimanual, retargeted to Inspire hands. 162 taxels/hand; fingertips, palm; not released. ACM MM 2026 ([paper](https://arxiv.org/abs/2607.09190), [project](https://tactidex.github.io/)).
- [TouchScale](https://touch-scale.github.io/) - Bimanual tactile gloves with 880 taxels per hand, recorded with head-mounted RGB-D and two wrist cameras across about 2K everyday tasks. 880 taxels/hand; fingertips, finger segments, palm; gated. arXiv 2610.10288 ([paper](https://arxiv.org/abs/2610.10288), [project](https://touch-scale.github.io/), [data](https://huggingface.co/datasets/2077AIDataFoundation/TouchScale), [code](https://github.com/phai-lab/touchscale)).
- [VICON](https://arxiv.org/abs/2610.05180) - Glove with force-sensing resistors and IMUs plus RGB-D for hand-object tracking with calibrated contact force. taxel count not stated; coverage not stated; release announced. arXiv 2610.05180 ([paper](https://arxiv.org/abs/2610.05180), [code](https://github.com/VICON-dataset/dataset)).
- [OpenTouch](https://opentouch-tactile.github.io/) - In-the-wild right-hand pressure glove with Meta Aria egocentric video, Rokoko hand pose and text labels across 14 environments. 169 taxels/hand; fingertips, finger segments, palm; public. arXiv 2512.16842 ([paper](https://arxiv.org/abs/2512.16842), [project](https://opentouch-tactile.github.io/), [data](https://github.com/OpenTouch-MIT/opentouch), [code](https://github.com/OpenTouch-MIT/opentouch)).
- [Reach&Grasp](https://doi.org/10.1038/s41597-025-04552-5) - Upper-limb reaching and grasping with a tactile glove, CyberGlove joint angles, Vicon motion capture and high-density EMG. 58 taxels/hand; fingertips, finger segments, palm; public. Scientific Data 2025 ([paper](https://doi.org/10.1038/s41597-025-04552-5), [code](https://github.com/DarioDiDomenico/SData_ReachGrasp)).
- [VTDexManip](https://proceedings.iclr.cc/paper_files/paper/2025/file/e19b6f65791e350347bcff8a3955cb5b-Paper-Conference.pdf) - Piezoresistive tactile gloves with egocentric HoloLens 2 video across 10 manipulation tasks and 182 objects, for visual-tactile pretraining. 20 taxels/hand; fingertips, palm; public. ICLR 2025 ([paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/e19b6f65791e350347bcff8a3955cb5b-Paper-Conference.pdf), [data](https://github.com/LQTS/VTDexManip), [code](https://github.com/LQTS/VTDexManip)).
- [ActionSense](https://action-sense.csail.mit.edu/) - Kitchen activities with bimanual tactile gloves, finger bend sensors, EMG, body IMUs, eye tracking and multi-view video. 682 taxels/hand; finger segments, palm; public. NeurIPS 2022 Datasets & Benchmarks ([paper](https://neurips.cc/virtual/2022/poster/55638), [project](https://action-sense.csail.mit.edu/), [data](https://action-sense.csail.mit.edu/data.html)).
- [ADL-21](https://pmc.ncbi.nlm.nih.gov/articles/PMC8068022/) - Tekscan Grip pressure system on the right hand of 22 subjects performing 21 activities of daily living. 361 taxels/hand; fingertips, finger segments, palm; public. Sensors 2021 ([paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC8068022/), [data](https://zenodo.org/records/4607289)).
- [Tactile textiles](https://senstextile.csail.mit.edu/) - Machine-knitted piezoresistive wearables including a full-hand glove; the glove data covers calibration and 26-object classification. taxel count not stated; fingertips, finger segments, palm; public. Nature Electronics 4 ([paper](https://doi.org/10.1038/s41928-021-00558-0), [project](https://senstextile.csail.mit.edu/), [data](https://github.com/YunzhuLi/senstextile), [code](https://github.com/YunzhuLi/senstextile)).
- [STAG](http://stag.csail.mit.edu/) - Knitted glove with 548 piezoresistive sensors over the whole hand; 135K frames of single-hand grasps on 26 objects. 548 taxels/hand; fingertips, finger segments, palm; public. Nature 569 ([paper](https://doi.org/10.1038/s41586-019-1234-z), [project](http://stag.csail.mit.edu/), [data](http://stag.csail.mit.edu/), [code](https://github.com/Erkil1452/touch)).

## Human-to-robot (paired human and robot touch)

- [DexViTac](https://xitong-c.github.io/DexViTac/) - Human demonstrations with fingertip tactile arrays, Manus hand pose and a fisheye camera, matched by identical sensors on an Inspire hand. 640 taxels/hand; fingertips; release announced. arXiv 2603.17851 ([paper](https://arxiv.org/abs/2603.17851), [project](https://xitong-c.github.io/DexViTac/), [data](https://huggingface.co/datasets/xitong-c/DexViTac_Dataset)).
- [HRDexDB](https://snuvclab.github.io/HRDexDB/) - Paired human and robot grasps (Allegro, two Inspire hands, Robotiq) with 21 cameras and object 6D pose; tactile on the robot fingertips only. taxel count not stated; fingertips; public. arXiv 2604.14944 ([paper](https://arxiv.org/abs/2604.14944), [project](https://snuvclab.github.io/HRDexDB/), [data](https://huggingface.co/datasets/HRDexDB/HRDexDB)).
- [TACROSS](https://tacross-touch-project.github.io/) - Piezoresistive fabric glove for large-scale human touch collection, paired with robot data from a capacitive Revo2 tactile hand. 256 taxels/hand; coverage not stated; release announced. arXiv 2610.11945 ([paper](https://arxiv.org/abs/2610.11945), [project](https://tacross-touch-project.github.io/)).
- [OSMO](https://www.jessicayin.com/osmo_tactile_glove/) - Open-source glove with three-axis magnetic taxels on fingertips and palm, worn by both the human demonstrator and the robot hand. 12 taxels/hand; fingertips, palm; not released. arXiv 2512.08920 ([paper](https://arxiv.org/abs/2512.08920), [project](https://www.jessicayin.com/osmo_tactile_glove/), [code](https://github.com/jessicayin/osmo_tactile_glove)).

## Tactile robot hands

- [RoboTacDex](https://arxiv.org/abs/2606.31836) - Visual-tactile-action trajectories on a Unitree G1 with dexterous hands across 19 tasks and 23 skills. taxel count not stated; coverage not stated; release announced. arXiv 2606.31836 ([paper](https://arxiv.org/abs/2606.31836)).
- [T-Rex](https://tactile-rex.github.io/) - Bimanual teleoperation on two 22-DoF Sharpa Wave hands with five fingertip tactile sensors each, in LeRobot format. 5 sensors/hand; fingertips; public. arXiv 2606.17055 ([paper](https://arxiv.org/abs/2606.17055), [project](https://tactile-rex.github.io/), [data](https://huggingface.co/datasets/zekaiwang/trex_dataset), [code](https://github.com/ZhuoyangLiu2005/T-Rex)).
- [Humanoid Everyday](https://humanoideveryday.github.io/) - Large humanoid manipulation dataset; the Unitree G1 episodes use Dex3-1 hands with tactile sensors. taxel count not stated; coverage not stated; availability unclear. arXiv 2510.08807 ([paper](https://arxiv.org/abs/2510.08807), [project](https://humanoideveryday.github.io/)).
- [Humanoid VTA](https://arxiv.org/abs/2510.25725) - Humanoid with two Inspire hands carrying 1,062 tactile sensors each over fingers and palm, teleoperated on deformable-object tasks. 1,062 taxels/hand; fingertips, finger segments, palm; not released. arXiv 2510.25725 ([paper](https://arxiv.org/abs/2510.25725)).
- [HATO](https://toruowo.github.io/hato/) - Bimanual teleoperation of two Psyonic Ability hands on UR5e arms, with fingertip pressure sensing and three RGB-D cameras. 30 taxels/hand; fingertips; public. ICRA 2025 ([paper](https://arxiv.org/abs/2404.16823), [project](https://toruowo.github.io/hato/), [data](https://github.com/toruowo/hato), [code](https://github.com/toruowo/hato)).
- [T-Dex](https://tactile-dexterity.github.io/) - Allegro hand covered with XELA uSkin pads, recorded during 2.5 hours of teleoperated play plus task demonstrations. 240 taxels/hand; fingertips, finger segments; public. CoRL 2023 ([paper](https://arxiv.org/abs/2303.12076), [project](https://tactile-dexterity.github.io/)).

<!-- END LIST -->

## Contributing

Add or correct an entry by editing [`data/datasets.json`](data/datasets.json) and running `python3 scripts/build_readme.py`, or [open an issue](../../issues/new/choose). Please cite a primary source (paper, project page or dataset card) for every number.

## Repository layout

| path | contents |
|---|---|
| `data/datasets.json` | the catalog: one record per dataset, the single source of truth |
| `index.html`, `assets/` | the catalog page (static, no build step) |
| `viewer/` | the synchronized video / tactile / hand-pose player; its media is served from the Hugging Face dataset [`yxma/human-mcap-viewer-media`](https://huggingface.co/datasets/yxma/human-mcap-viewer-media) |
| `scripts/build_readme.py` | validates the catalog and regenerates the list above |
| `scripts/fetch_thumbs.py` | caches each dataset's overview figure in `assets/thumbs/` |

## License

Code: MIT. Catalog text and data: CC BY 4.0. Figures belong to their authors and are shown for identification, linked to their source.
