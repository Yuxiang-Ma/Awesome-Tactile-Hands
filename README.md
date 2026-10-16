# Awesome Tactile Hands [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> **Taxel Atlas**: a curated catalog of public datasets that record touch across the hand during manipulation, from human tactile gloves to dexterous robot hands with tactile skins.

Browse, filter and compare them on the [live catalog](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/), play recorded samples in the [data viewer](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/viewer/), see the gloves, robot hands and sensors they were recorded with on the [hardware page](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/hardware.html), and read how each dataset's hand pose was captured, with input and output formats and published accuracy, on the [hand pose page](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/pose.html).

**What gets in.** Tactile sensing *on the hand* (glove or robot hand), recorded while the hand manipulates objects, with data that is released or announced. Each entry states which regions are sensed (fingertips, finger segments, palm), how many taxels per hand, what else is recorded in sync, and how to get it. Numbers are as the authors report them; anything we could not confirm from a primary source is marked as not stated.

**What stays out.** Contact estimated from cameras, pressure pads under the hand, or thermal contact maps on objects (PressureVision, EgoPressure, ContactPose, ContactDB); parallel-jaw grippers; tactile hardware papers with no data.

<!-- BEGIN LIST -->
**22** datasets · updated 2026-10-15

## Ranks

Each entry carries a rank for how open and verified its data is, after the evidence ranking of the [MIT CDFG survey](https://mit-cdfg.github.io/Survey-AI-for-3D-modeling-Robotics/#sub-manipulation-evaluations), and a quality score counting touch in physical units (N, kPa), synchronized camera video, finger pose or joint tracking, 10 h or 1,000 episodes or more, 10 tasks or 5 environments or more.

| rank | meaning | datasets |
|---|---|---|
| `R1` Open + checked | public download, license stated, and sample episodes converted and checked in the viewer | ActionSense, Humanoid Everyday, T-Rex, VTDexManip, HRDexDB, ADL-21, EgoTactile, Reach&Grasp |
| `R2` Open | public download, but the license is not stated or the files have not been checked yet | EgoTouch, OpenTouch, HATO, T-Dex, STAG, Tactile textiles |
| `R3` Restricted | gated, on request, or only a partial sample released | TouchScale, OSMO |
| `R4` Paper only | announced or described in a paper, no data released | DexViTac, RoboTacDex, TACROSS, VICON, Humanoid VTA, TactiDex |

## Human tactile gloves

- `R1` `Q2/5` [EgoTactile](https://egotactile.github.io/) - Full-hand 162-sensor pressure glove with egocentric video of grasps on 63 everyday objects, plus a bare-hand test set. 162 taxels/hand; fingertips, finger segments, palm; 5.82 h; cameras: egocentric; hand tracking: none; public. ICML 2026 ([paper](https://arxiv.org/abs/2606.09243), [project](https://egotactile.github.io/), [data](https://huggingface.co/datasets/HustleHard/EgoTactile), [code](https://github.com/Russell-Zeng/EgoTactile)).
- `R2` `Q4/5` [EgoTouch](https://jianyi2004.github.io/TouchAnything-Website/) - Bimanual pressure gloves with Rokoko finger tracking and Vive wrist trackers, a chest camera and two fisheye wrist cameras, 208 tasks in 5 kinds of scenes. 123 taxels/hand; fingertips, finger segments, palm; 20 h, 208 tasks, 5 environments; cameras: egocentric + 2 wrist; hand tracking: IMU (Rokoko Smartgloves); Vive tracker (HTC Vive Tracker); vision (WiLoR, HaMeR); public. arXiv 2605.13083 ([paper](https://arxiv.org/abs/2605.13083), [project](https://jianyi2004.github.io/TouchAnything-Website/), [data](https://huggingface.co/datasets/zhouzhoujy/EgoTouch), [code](https://github.com/Jianyi2004/TouchAnything)).
- `R4` `Q2/5` [TactiDex](https://tactidex.github.io/) - Piezoresistive glove over a MANUS mocap glove with OptiTrack object tracking, single-hand and bimanual, retargeted to Inspire hands. 162 taxels/hand; fingertips, palm; 11.8 h; cameras: none; hand tracking: IMU (MANUS Metagloves Pro); optical mocap (OptiTrack, 8x PrimeX 13W at 120 fps); not released. ACM MM 2026 ([paper](https://arxiv.org/abs/2607.09190), [project](https://tactidex.github.io/)).
- `R3` `Q4/5` [TouchScale](https://touch-scale.github.io/) - Bimanual tactile gloves with 880 taxels per hand, recorded with head-mounted RGB-D and two wrist cameras across about 2K everyday tasks. 880 taxels/hand; fingertips, finger segments, palm; 500 h, 2,000 tasks, 9 environments; cameras: egocentric + 2 wrist; hand tracking: vision (WiLoR); gated. arXiv 2610.10288 ([paper](https://arxiv.org/abs/2610.10288), [project](https://touch-scale.github.io/), [data](https://huggingface.co/datasets/2077AIDataFoundation/TouchScale), [code](https://github.com/phai-lab/touchscale)).
- `R4` `Q3/5` [VICON](https://arxiv.org/abs/2610.05180) - Glove with eight force-sensing resistors and an IMU/marker hand tracker, recorded with a static RGB-D camera for hand-object pose with calibrated contact force. 8 taxels/hand; fingertips, palm; 0.75 h, 1 tasks; cameras: 1 third-person; hand tracking: IMU (VIST glove); release announced. arXiv 2610.05180 ([paper](https://arxiv.org/abs/2610.05180), [code](https://github.com/VICON-dataset/dataset)).
- `R2` `Q4/5` [OpenTouch](https://opentouch-tactile.github.io/) - In-the-wild right-hand pressure glove with Meta Aria egocentric video, Rokoko hand pose and text labels across 14 environments. 169 taxels/hand; fingertips, finger segments, palm; 5.1 h, 14 environments; cameras: egocentric; hand tracking: IMU (Rokoko Smartgloves); public. arXiv 2512.16842 ([paper](https://arxiv.org/abs/2512.16842), [project](https://opentouch-tactile.github.io/), [data](https://github.com/OpenTouch-MIT/opentouch), [code](https://github.com/OpenTouch-MIT/opentouch)).
- `R3` `Q2/5` [OSMO](https://www.jessicayin.com/osmo_tactile_glove/) - Open-source glove with 12 three-axis magnetic taxels on fingertips and palm; ~2 h of right-hand whiteboard-wiping demonstrations with a static RealSense D435 (RGB + IR stereo), of which one 8.4 s sample is released. 12 taxels/hand; fingertips, palm; 2 h, 1 tasks; cameras: 2 third-person; hand tracking: vision (SAM2 mask + HaMeR); vision (HaMeR wrist refined with FoundationStereo depth from the IR pair); partial. arXiv 2512.08920 ([paper](https://arxiv.org/abs/2512.08920), [project](https://www.jessicayin.com/osmo_tactile_glove/), [data](https://drive.google.com/drive/folders/1SSE9pQetSoLbk82gnHd8Z3xHq7doRGgf), [code](https://github.com/jessicayin/osmo_tactile_glove)).
- `R1` `Q2/5` [Reach&Grasp](https://doi.org/10.1038/s41597-025-04552-5) - 10 subjects perform 16 right-arm tasks (hand and wrist movements, grasps, reach-grasp-manipulate) wearing a Bielefeld sensorized glove (58 piezoresistive taxels plus CyberGlove I bend sensors), with Vicon joint angles and bipolar and high-density EMG. 58 taxels/hand; fingertips, finger segments, palm; 2.76 h, 16 tasks; cameras: none; hand tracking: optical mocap (Vicon); optical mocap (Vicon Plug-in Gait model); bend sensors (CyberGlove I); public. Scientific Data 12:233, 2025 ([paper](https://doi.org/10.1038/s41597-025-04552-5), [data](https://doi.org/10.48557/L6OWMM), [code](https://github.com/DarioDiDomenico/SData_ReachGrasp)).
- `R1` `Q4/5` [VTDexManip](https://lqts.github.io/VTDexManip/) - Human right-hand manipulation with a 20-pad piezoresistive tactile glove, recorded as egocentric HoloLens 2 frames paired one-to-one with pad voltages: 2,032 sequences, 10 tasks, 182 objects, 5 subjects. 20 taxels/hand; fingertips, finger segments, palm; 10 tasks; cameras: egocentric; hand tracking: none; public. ICLR 2025 ([paper](https://proceedings.iclr.cc/paper_files/paper/2025/file/e19b6f65791e350347bcff8a3955cb5b-Paper-Conference.pdf), [project](https://lqts.github.io/VTDexManip/), [data](https://1drv.ms/f/c/9054151f0ba654c9/EslUpgsfFVQggJB7AQAAAAABSp31p8Fft1mtHyOwJNqmoA), [code](https://github.com/LQTS/VTDexManip)).
- `R1` `Q4/5` [ActionSense](https://action-sense.csail.mit.edu/) - Kitchen activities in a mock kitchen with bimanual 32x32 conductive-thread tactile gloves, Manus bend-sensor finger tracking, Xsens body IMUs, Myo forearm EMG, Pupil Core eye tracking, 5 static RGB cameras and 2 microphones. 682 taxels/hand; finger segments, palm; 13 h, 20 tasks; cameras: egocentric + 6 third-person; hand tracking: IMU (Xsens MTw Awinda); bend sensors (Manus Prime II Xsens gloves); public. NeurIPS 2022 Datasets & Benchmarks ([paper](https://openreview.net/forum?id=olvz0gAdGOX), [project](https://action-sense.csail.mit.edu/), [data](https://action-sense.csail.mit.edu/data.html), [code](https://github.com/delpreto/ActionNet)).
- `R1` `Q2/5` [ADL-21](https://doi.org/10.3390/s21082594) - Tekscan Grip 4256E pressure sensor (361 sensels) sewn on a glove on the right hand of 22 subjects, each performing 21 activities of daily living once. 361 taxels/hand; fingertips, finger segments, palm; 1.8 h, 21 tasks, 6 environments; cameras: none; hand tracking: none; public. Sensors 21(8):2594, 2021 ([paper](https://doi.org/10.3390/s21082594), [data](https://zenodo.org/records/4607289)).
- `R2` `Q1/5` [Tactile textiles](https://senstextile.csail.mit.edu/) - Machine-knitted piezoresistive glove (722 sensors, 32x32 readout) worn by one person; released glove data is raw pressure maps while holding 27 objects or the bare hand, plus pressing on a digital scale, a tactile vest and a robot-arm sleeve for calibration. 722 taxels/hand; fingertips, finger segments, palm; 10.75 h; cameras: none; hand tracking: IMU (Xsens MVN); public. Nature Electronics 4 ([paper](https://doi.org/10.1038/s41928-021-00558-0), [project](https://senstextile.csail.mit.edu/), [data](https://www.dropbox.com/sh/g70n60jfutzd0l5/AACnOgtLUG8tHbU8TLn5MBFba?dl=0), [code](https://github.com/YunzhuLi/senstextile)).
- `R2` `Q1/5` [STAG](http://stag.csail.mit.edu/) - Knitted glove with 548 piezoresistive sensors over the palmar side of the right hand, read as a 32x32 grid at ~7.3 Hz; one subject grasping 26 objects, plus blindfolded, weight and hand-pose sets with synchronized RGB frames. 548 taxels/hand; fingertips, finger segments, palm; 6.9 h, 4 tasks; cameras: 1 third-person; hand tracking: none; public. Nature 569(7758), 2019 ([paper](https://doi.org/10.1038/s41586-019-1234-z), [project](http://stag.csail.mit.edu/), [data](http://stag.csail.mit.edu/#data), [code](https://github.com/Erkil1452/touch)).

## Human-to-robot (paired human and robot touch)

- `R4` `Q4/5` [DexViTac](https://xitong-c.github.io/DexViTac/) - Human demonstrations with fingertip tactile arrays, Manus finger tracking and a hand-mounted fisheye camera, matched by identical sensors on an Inspire hand. 640 taxels/hand; fingertips; 40 tasks, 10 environments; cameras: 2 wrist; hand tracking: magnetic (Manus Quantum Metagloves); other (Intel RealSense T265); joint encoders (RealMan RM-65 6-DoF arm + Inspire RH56DFTP); release announced. arXiv 2603.17851 ([paper](https://arxiv.org/abs/2603.17851), [project](https://xitong-c.github.io/DexViTac/), [data](https://huggingface.co/datasets/xitong-c/DexViTac_Dataset)).
- `R1` `Q3/5` [HRDexDB](https://snuvclab.github.io/HRDexDB/) - Paired human and teleoperated robot grasps (Allegro V5 Plus, Inspire RH56F1 and RH56DFTP, Robotiq 2F-85 on an xArm6) over 100 objects, filmed by a 23-camera rig with MANO hands and object 6D poses; built-in tactile only on the Allegro and Inspire F1 hands. taxel count not stated; fingertips, palm; 14.9 h, 1 tasks; cameras: 21 third-person + 4 egocentric; hand tracking: vision (HaMeR 2D keypoints in calibrated views -> triangulation -> MANO fit); joint encoders (robot hand joint states and commands); joint encoders (xArm6 joint position/velocity/torque + 4x4 pose action); teleop glove (MANUS gloves); Vive tracker (HTC Vive wrist tracker); public. arXiv 2604.14944 ([paper](https://arxiv.org/abs/2604.14944), [project](https://snuvclab.github.io/HRDexDB/), [data](https://huggingface.co/datasets/HRDexDB/HRDexDB), [code](https://github.com/snuvclab/HRDexDB)).
- `R4` `Q3/5` [TACROSS](https://tacross-touch-project.github.io/) - Piezoresistive fabric glove for large-scale human touch collection, paired with robot data from a capacitive Revo2 tactile hand. 256 taxels/hand; fingertips, finger segments, palm; 183.95 h; cameras: egocentric + 3 other; hand tracking: vision (HaMeR); IMU (Rokoko motion-capture glove); joint encoders (7-DoF arm); release announced. arXiv 2610.11945 ([paper](https://arxiv.org/abs/2610.11945), [project](https://tacross-touch-project.github.io/)).

## Tactile robot hands

- `R4` `Q4/5` [RoboTacDex](https://arxiv.org/abs/2606.31836) - Visual-tactile-action trajectories on a Unitree G1 with dexterous hands across 19 tasks and 23 skills. taxel count not stated; fingertips; 25 h, 19 tasks; cameras: 1 robot head + 1 third-person + 2 wrist; hand tracking: joint encoders (Unitree G1); vision (Meta Horizon VR headset); release announced. arXiv 2606.31836 ([paper](https://arxiv.org/abs/2606.31836)).
- `R1` `Q4/5` [T-Rex](https://tactile-rex.github.io/) - Bimanual teleoperation on two 22-DoF Sharpa Wave hands with five fingertip tactile sensors each, in LeRobot format. 5 sensors/hand; fingertips; 50 h, 22 tasks, 6 environments; cameras: 1 robot head + 2 wrist; hand tracking: joint encoders (Sharpa Wave 22-DoF hand joint states); joint encoders (Dexmate Vega-1 arm joint encoders); teleop glove (Manus gloves); Vive tracker (HTC VIVE trackers); public. arXiv 2606.17055 ([paper](https://arxiv.org/abs/2606.17055), [project](https://tactile-rex.github.io/), [data](https://huggingface.co/datasets/zekaiwang/trex_dataset), [code](https://github.com/ZhuoyangLiu2005/T-Rex)).
- `R1` `Q4/5` [Humanoid Everyday](https://humanoideveryday.github.io/) - Teleoperated Unitree G1 and H1 humanoids on 246 everyday tasks; the G1 episodes carry Unitree Dex3-1 hand pressure sensors (9 per hand). 33 taxels/hand; fingertips, finger segments, palm; 31.8 h, 246 tasks; cameras: 1 robot head; hand tracking: joint encoders (Dex3-1); joint encoders (Unitree G1); vision (Apple Vision Pro hand tracking); public. arXiv 2510.08807 ([paper](https://arxiv.org/abs/2510.08807), [project](https://humanoideveryday.github.io/), [data](https://huggingface.co/datasets/USC-PSI-Lab/humanoid-everyday), [code](https://github.com/physical-superintelligence-lab/Humanoid-Everyday)).
- `R4` `Q2/5` [Humanoid VTA](https://arxiv.org/abs/2510.25725) - Humanoid with two Inspire hands carrying 1,062 tactile sensors each over fingers and palm, teleoperated on deformable-object tasks. 1,062 taxels/hand; fingertips, finger segments, palm; 4 tasks; cameras: 1 robot head + 1 third-person; hand tracking: joint encoders (Inspire RH56DFX finger joint positions); joint encoders (Unitree G1 arm joint positions); vision (Apple Vision Pro hand tracking); not released. arXiv 2510.25725 ([paper](https://arxiv.org/abs/2510.25725)).
- `R2` `Q2/5` [HATO](https://toruowo.github.io/hato/) - Bimanual teleoperation of two Psyonic Ability hands on UR5e arms, with fingertip pressure sensing and three RGB-D cameras. 30 taxels/hand; fingertips; 6.2 h, 4 tasks; cameras: 2 wrist + 1 third-person; hand tracking: joint encoders (PSYONIC Ability Hand finger positions); joint encoders (UR5e joint encoders + EEF pose); other (Meta Quest 2 controllers); other (Meta Quest 2 controller buttons/triggers); public. ICRA 2025 ([paper](https://arxiv.org/abs/2404.16823), [project](https://toruowo.github.io/hato/), [data](https://github.com/toruowo/hato), [code](https://github.com/toruowo/hato)).
- `R2` `Q2/5` [T-Dex](https://tactile-dexterity.github.io/) - Teleoperated Allegro hand on a Kinova Jaco arm with 15 XELA uSkin 4x4 three-axis pads, recorded as task-agnostic play plus demonstrations of 5 contact-rich tasks. 240 taxels/hand; fingertips, finger segments; 1.71 h, 5 tasks; cameras: 2 third-person; hand tracking: joint encoders (Allegro hand joint states); joint encoders (Kinova Jaco joint states); vision (Holo-Dex with an Oculus headset); other (Kinova built-in joystick); public. CoRL 2023 (PMLR 229) ([paper](https://arxiv.org/abs/2303.12076), [project](https://tactile-dexterity.github.io/), [data](https://drive.google.com/drive/folders/148ycBmuvqkdESvAhStlhYJ7ISMgelEvL), [code](https://github.com/irmakguzey/tactile-dexterity)).

## Hardware

**69** devices, 28 of them used by the datasets above. Photos, specs and a hardware-to-dataset map are on the [hardware page](https://yuxiang-ma.github.io/Awesome-Tactile-Hands/hardware.html).

### Tactile gloves

- [ActionSense tactile glove](https://action-sense.csail.mit.edu/) - MIT CSAIL (Matusik lab), 2022; research only; 682 taxels per hand, computed from the stated grids (23x19 palm + 5x9 thumb + 11x4 little finger + 3 x 13x4 other fingers); raw readout is a 32x32 matrix; piezoresistive. Used in: ActionSense.
- [EgoTactile pressure glove (162-sensor)](https://egotactile.github.io/) - not named (EgoTactile authors, Tsinghua SIGS; a co-author is affiliated with JQ Industries), 2026; research only; 162 taxels per glove (raw 256-channel vector, 162 used). Used in: EgoTactile.
- [Fabric Tactile Glove](https://jq-industries.com/precision/glove) - JQ Industries (矩侨工业, Weihai), 2025; commercial; 256 taxels raw channels per hand as streamed in EgoTouch (16 x 16); the release maps about 123 pressure taxels plus 15-24 finger bend sensors. JQ lists 139 sensing points for the glove in its Unitree G1 skin set.. Used in: EgoTouch.
- [Knitted tactile glove (tactile textiles)](https://senstextile.csail.mit.edu/) - MIT CSAIL (Matusik lab), 2021; research only; 722 taxels per glove (722 sensors over 160 cm2); piezoresistive. Used in: Tactile textiles.
- [OpenTouch Glove](https://wiresens-gloves.vercel.app/) - MIT CSAIL (Matusik lab), 2025; open hardware; 169 taxels per hand (16 x 16 electrode grid routed into 169 taxels, palmar side); piezoresistive. Used in: OpenTouch.
- [OSMO tactile glove](https://shop.wowrobo.com/products/osmo-tactile-glove) - Meta FAIR, 2025; open hardware; 12 taxels per glove: 12 three-axis taxels (5 fingertips + 7 on the palm in three sections); magnetic. Used in: OSMO.
- [STAG (scalable tactile glove)](http://stag.csail.mit.edu/) - MIT CSAIL (Matusik lab), 2019; research only; 548 taxels per glove (64 electrodes, 32x32 readout, 548 valid crossings); piezoresistive. Used in: STAG.
- [TachinGlove](https://www.tachin.com/en/solutions?category=embodied&series=ei-g) - Tachin Technology (途见科技, Beijing), 2026; commercial; 880 taxels per glove (TouchScale paper); the quick-release TachinGloveSnap variant has 783. Used in: TouchScale.
- [TACROSS tactile glove](https://tacross-touch-project.github.io/) - The University of Hong Kong / INFIFORCE, 2026; open hardware; 285 taxels per glove: 285 physical sensing locations (12x15 palm + five 3x7 finger arrays); 256 values streamed per frame; piezoresistive. Used in: TACROSS.
- [TactiDex tactile glove (162-element)](https://tactidex.github.io/) - ShanghaiTech University (TactiDex authors; base glove vendor not named), 2026; research only; 162 taxels per glove; piezoresistive. Used in: TactiDex.
- [Tactile dataglove (fabric-based sensors)](https://doi.org/10.1109/HUMANOIDS.2012.6651521) - Bielefeld University (CITEC, Neuroinformatics group), 2012; research only; 58 taxels per hand, version used in Reach&Grasp (the 2012 paper describes 54 cells); piezoresistive. Used in: Reach&Grasp.
- [VTDexManip tactile glove](https://lqts.github.io/VTDexManip/) - Zhejiang University (Qi Ye group), 2025; research only; 20 taxels per glove (20 discrete thin-film pressure sensors); piezoresistive. Used in: VTDexManip.
- [ART-Glove](https://linchangyi1.github.io/ART-Glove/) - Carnegie Mellon University (Ding Zhao lab), 2026; research only; 2,048 taxels per glove; piezoresistive.
- [DAS Dex](https://www.genrobot.ai/products/dex) - GenRobot AI; commercial.
- [Flex-Glove](https://arxiv.org/abs/2503.06349) - MIT CSAIL (Matusik lab), 2025; open hardware; piezoresistive.
- [FusionX V3 thin-film glove](https://github.com/TouchTronix-Robotics/FusionX-DataCollection) - TouchTronix Robotics; commercial; 80 taxels per glove: five 4x4 patches, one per finger; no palm channels.
- HANDX tactile glove - Shouzhi Innovation (HANDX), 2026; commercial; 45 taxels standard per hand (3x3 per fingertip); optional up to 800.
- [loadglove](https://novel.de/products/buttonsens/loadglove/) - novel GmbH; commercial; capacitive.
- [pliance glove system](https://novel.de/products/pliance/glove-force-measurement/) - novel GmbH; commercial; capacitive.
- [ProGlove Gen 1](https://www.proception.ai/product/pro-glove/gen1) - Proception, 2026; announced.
- [PXCap III](https://www.paxini.com/en/ax/pxcap3) - PaXini; commercial; magnetic.
- [PXCap Pro](https://www.paxini.com/en/ax/pxcapProp) - PaXini; commercial; 1,743 taxels tactile signals per glove (vendor count).
- [RC G1 Tactile Glove](https://www.roboticscenter.ai/store/product/rc-g1-tactile-glove) - Robotics Center (RCSV); commercial; 162 taxels per hand (fingers + palm).
- [Skin](https://6thsense.dev/products) - 6thSense, 2026; announced; 464 taxels sensing channels per hand.
- Tacknit Glove G1 - Yaole Technology, 2026; commercial; 216 taxels per glove.
- [Tacta Glove](https://www.tactasystems.com/) - Tacta Systems; announced.
- [TactileGlove II](https://pressureprofile.com/tactile-glove) - Pressure Profile Systems (PPS), 2020; commercial; 65 taxels per glove; elements 5.0 x 6.0 mm; capacitive.
- [Tactilus sensor glove](https://www.sensorprod.com/applications/grip-pressure-sensor-glove/) - Sensor Products Inc.; commercial; 24 taxels per glove; 7.95 x 7.95 mm sensors; piezoresistive.
- [Wuji Glove](https://wuji.tech/en/glove) - Wuji Technology; commercial; 526 taxels active points in a 24 x 31 pressure matrix per glove.

### Tactile robot hands

- [RH56DFTP (now listed as RH56E2)](https://en.inspire-robots.com/product-category/the-dexterous-hands/rh56e2/) - Inspire Robots (Beijing Inspire-Robots Technology Co., Ltd.), 2024; commercial; 1,062 taxels per hand, piezoresistive version (RH56DFTP-0L/0R, -2L/2R): 17 regions; each finger 3x3 tip + 12x8 nail + 10x8 pad, thumb 3x3 tip + 12x8 nail + 3x3 middle + 12x8 pad, palm 8x14; piezoresistive. Used in: HRDexDB, DexViTac, Humanoid VTA.
- [Revo2 TOUCH (tactile version, XTL/XTR)](https://www.brainco-hz.com/docs/revolimb-hand/en/revo2/parameters.html) - BrainCo (Zhejiang Qiangnao Technology Co., Ltd.), 2025; commercial; 5 taxels per hand, capacitive version: one 3D force + proximity reading per fingertip, each derived from 6 capacitive channels; capacitive. Used in: TACROSS, RoboTacDex.
- [Ability Hand](https://www.psyonic.io/robots) - PSYONIC, 2019; commercial; 30 taxels per hand: 30 force-sensing resistors, 6 per digit; piezoresistive. Used in: HATO.
- [Allegro Hand V5 Plus](https://www.allegrohand.com/sub/product/p.php?idx=4) - Wonik Robotics; commercial; 4 taxels per hand: one pneumatic (air-pressure) sensor per fingertip on the 4-finger V5 Plus; barometric. Used in: HRDexDB.
- [Dex3-1](https://www.unitree.com/Dex3-1/) - Unitree Robotics, 2024; commercial; 33 taxels per hand: 9 array sensors - 3 palm arrays 2x2, 3 finger-pad arrays 2x2, 3 fingertip arrays 3x1. Used in: Humanoid Everyday.
- [RH56F1](https://en.inspire-robots.com/product-category/the-dexterous-hands/rh56f1/) - Inspire Robots (Beijing Inspire-Robots Technology Co., Ltd.), 2025; commercial; 8 taxels per hand: 8 force-sensing sites (5 fingertips + 3 palm regions), each reporting normal force, tangential force and tangential direction; fingertips also report a 24-bit proximity value; capacitive. Used in: HRDexDB.
- [SharpaWave (Wave W01)](https://www.sharpa.com/pages/w01) - Sharpa, 2025; commercial; optical. Used in: T-Rex.
- [DEX-EE / DEX-EE Chiral](https://shadowrobot.com/dex-ee/) - Shadow Robot Company (developed with Google DeepMind), 2024; commercial; 108 taxels per 3-finger hand: magnetic phalanx cells only (22 proximal + 14 middle per finger); the 3 optical fingertips (stereo cameras tracking 525 internal markers each) are not counted; optical.
- [Dex5-1P (tactile version of Dex5-1)](https://www.unitree.com/Dex5-1/) - Unitree Robotics, 2025; commercial; 94 taxels per hand: palm 2x5, fingertip 2x3 x5, finger pad 2x3 x5, finger root 2x3 x4 (no thumb root).
- [DexH13 (GEN2)](https://www.paxini.com/en/dex/gen2) - PaXini Tech, 2024; commercial; 1,140 taxels per hand: ITPU multidimensional tactile sensing units, 3 axes each (3,420 signal channels); magnetic.
- [DG-5F-M / DG-5F-S with fingertip tactile sensors](https://www.tesollo.com/products/grippers/dg-5f-m) - Tesollo, 2025; commercial; 75 taxels per hand with tactile fingertips on all 5 fingers: 3x5 nodes per tip (DG-5F-M); DG-5F-S tips have 3x6 nodes = 90.
- [Linker Hand (tactile models: L20, L20 Lite, L30 Pro, L6, O6)](https://www.linkerbot.cn/details/LinkerHandL20) - LinkerBot; commercial; 360 taxels per hand: one 6x12 piezoresistive array per fingertip x 5 (L20 and L20 Lite manuals); piezoresistive.
- [RH8D with FTS fingertip sensors](https://www.seedrobotics.com/rh8d-adult-robot-hand) - Seed Robotics; commercial; 5 taxels per hand: one single-point FTS force sensor per fingertip (FTS-3: 3-axis; FTS-1: normal only).
- [ROBOTIS Hand HX5-D20](https://ai.robotis.com/hands/introduction_hands.html) - ROBOTIS, 2026; commercial; 45 taxels per hand: 3x3 pressure array (TIP sensor) on each of 5 fingertips, 8-bit values.
- [Shadow Dexterous Hand (Series E)](https://www.shadowrobot.com/dexterous-hand-series/) - Shadow Robot Company; commercial; 85 taxels per hand with all 5 Shadow Tactile Fingertips (17 taxels each, 3-axis Hall); standard build has 2 STFs (thumb, index) = 34; magnetic.
- [Wuji Hand 2 (fingertip tactile version, Beta 2.2)](https://www.wuji.tech/en/hand2) - Wuji Technology, 2026; announced; 176 taxels per hand: 40 contact points on the thumb tip + 34 on each of the other four fingertips; each point reports 3-axis force.
- [XHAND 1](https://www.robotera.com/en/product/XHAND) - ROBOTERA (Beijing Xingdong Jiyuan), 2024; commercial; 600 taxels per hand: 5 fingertip arrays x 120 points (12x10), each wrapping 270 deg around the fingertip.

### Add-on tactile sensors

- [FSR 400 series](https://www.interlinkelectronics.com/fsr-400) - Interlink Electronics; commercial; 1 taxels single-zone sensor; the VICON glove uses 8; piezoresistive. Used in: VICON.
- [Grip System (sensor 4256E)](https://www.tekscan.com/products-solutions/systems/grip-system) - Tekscan; commercial; 361 taxels sensels per 4256E hand sensor (one hand); piezoresistive. Used in: ADL-21.
- [LongLin-96 (龙鳞96)](https://www.whhit.cn/product/info/11.html) - Wuhan Huaweike Intelligent Technology (HIT 华威科); commercial; 96 taxels per module (vendor: 12 x 8 array, 1.2 mm pitch); DexViTac paper reports 8 x 16; piezoresistive. Used in: DexViTac.
- [uSkin for Allegro Hand V4 Curved](https://xelarobotics.com/products/for-allegro-hand-v4-curved/) - XELA Robotics; commercial; 368 taxels per hand (current kit): 4 fingertips x 30 + 11 phalanges x 16 + 72 palm sensing points, each 3-axis; 1,472 measurements incl. temperature; magnetic. Used in: T-Dex.
- [9DTact](https://linchangyi1.github.io/9DTact/) - Tsinghua University IIIS / Shanghai Qi Zhi Institute (Huazhe Xu lab), 2023; open hardware; optical.
- [AnySkin](https://any-skin.github.io/) - New York University (Lerrel Pinto lab), with CMU, Columbia and Meta AI, 2024; open hardware; 5 taxels magnetometers per skin board (3-axis each, 15 channels); magnetic.
- [BioTac](https://syntouchinc.com/robotics/) - SynTouch, 2008; discontinued; 19 taxels impedance-sensing electrodes per fingertip (plus one fluid-pressure transducer and a thermistor); resistive.
- [DIGIT](https://www.gelsight.com/product/digit-tactile-sensor/) - Meta AI (FAIR); manufactured and sold by GelSight Inc., 2020; commercial; optical.
- [Digit 360](https://digit.ml/digit360) - Meta FAIR, with GelSight Inc., 2024; announced; 8,300,000 taxels ~8.3 million taxels per fingertip as stated by Meta (camera-based, hemispherical); optical.
- [DM-Tac F (fingertip) and DM-Tac series vision-based tactile sensors](https://www.dmrobot.com/en/devices/dm-tac-f.html) - Daimon Robotics, 2025; commercial; optical.
- [FingerTPS II](https://pressureprofile.com/finger-tps) - Pressure Profile Systems (PPS); commercial; capacitive.
- [GelSight Mini](https://www.gelsight.com/gelsightmini/) - GelSight Inc., 2022; commercial; optical.
- [PapillArray Tactile Sensor (v2.0)](https://contactile.com/products/#development-kit) - Contactile, 2019; commercial; 9 taxels silicone pillars per 3x3 array, each with 3D displacement and 3D force; optical.
- [PX-6AX tactile sensors (GEN3 / GEN4)](https://www.paxini.com/en/ax/gen3) - PaXini Tech; commercial; magnetic.
- [ReSkin](https://reskin.dev/) - Meta AI (FAIR) / Carnegie Mellon University, 2021; open hardware; 5 taxels MLX90393 magnetometers per 20 x 20 mm board (Bx, By, Bz + temperature each); magnetic.
- [TacTip (TacTip family)](https://softroboticstoolkit.com/tactip) - Bristol Robotics Laboratory (Nathan Lepora lab, University of Bristol), 2009; open hardware; optical.
- [Tashan TS-F / TS-E tactile sensors](https://www.tashantec.com/robot) - Tashan Technology (他山科技), Beijing, 2025; commercial; 7 taxels raw capacitance channels per TS-F-A fingertip module (vendor simulation repo); capacitive.
- [uSkin](https://xelarobotics.com/products/) - XELA Robotics, 2018; commercial; 16 taxels per module, for the uSPa 44 reference patch (4x4); modules range from 1 (uSPa 11) to 30 (uSCu fingertip), up to 64 per module; magnetic.

### Hand-tracking gloves used with tactile gloves

- [Smartgloves](https://www.rokoko.com/products/smartgloves) - Rokoko; commercial. Used in: EgoTouch, OpenTouch, TACROSS.
- [Metagloves Pro](https://www.manus-meta.com/products/metagloves-pro) - MANUS, 2024; commercial. Used in: TactiDex, T-Rex.
- [CyberGlove (wired, 'CyberGlove I')](http://www.cyberglovesystems.com/) - CyberGlove Systems; discontinued. Used in: Reach&Grasp.
- [Prime II Xsens](https://web.archive.org/web/20201222173437/https://manus-vr.com/prime-2-xsens) - MANUS, 2020; discontinued. Used in: ActionSense.
- [Quantum Metagloves](https://www.manus-meta.com/products/quantum-metagloves) - MANUS, 2022; discontinued. Used in: DexViTac.

<!-- END LIST -->

## Contributing

Add or correct an entry by editing [`data/datasets.json`](data/datasets.json) or [`data/hardware.json`](data/hardware.json) and running `python3 scripts/build_readme.py`, or [open an issue](../../issues/new/choose). Please cite a primary source (paper, project page or dataset card) for every number.

## Repository layout

| path | contents |
|---|---|
| `data/datasets.json` | the catalog: one record per dataset, the single source of truth |
| `data/hardware.json` | tactile gloves, tactile robot hands and add-on sensors, each with the catalog datasets recorded with it |
| `index.html`, `hardware.html`, `assets/` | the catalog and hardware pages (static, no build step) |
| `viewer/` | the synchronized video / tactile / hand-pose player; its media is served from the Hugging Face dataset [`yxma/human-mcap-viewer-media`](https://huggingface.co/datasets/yxma/human-mcap-viewer-media) |
| `scripts/build_readme.py` | validates both files and regenerates the lists above |
| `scripts/fetch_thumbs.py` | caches each dataset's overview figure in `assets/thumbs/` and each device photo in `assets/hw/` |
| `pipeline/` | how a dataset is surveyed, sampled, converted for the viewer and checked |

## License

Code: MIT. Catalog text and data: CC BY 4.0. Figures and product photos belong to their authors and makers and are shown for identification, linked to their source.
