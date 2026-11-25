"""Load the YOLO checkpoints bundled with the project."""
from contextlib import nullcontext
from pathlib import Path

import torch
from ultralytics import YOLO
from ultralytics.nn.modules import Bottleneck, C2f, Concat, Conv, Detect, DFL, Pose, SPPF
from ultralytics.nn.tasks import DetectionModel, PoseModel
from ultralytics.utils import IterableSimpleNamespace
from ultralytics.utils.loss import BboxLoss, v8DetectionLoss
from ultralytics.utils.tal import TaskAlignedAssigner

CHECKPOINT_CLASSES = [
    torch.nn.SiLU, torch.nn.BatchNorm2d, torch.nn.ModuleList, torch.nn.Sequential,
    torch.nn.Conv2d, torch.nn.BCEWithLogitsLoss, torch.nn.MaxPool2d, torch.nn.Upsample,
    Bottleneck, C2f, Concat, Conv, Detect, DFL, SPPF, DetectionModel,
    IterableSimpleNamespace, BboxLoss, v8DetectionLoss, TaskAlignedAssigner,
]


def _legacy_detect_forward(cls, name):
    # The face checkpoint serialized exactly the unbound Detect.forward method.
    if cls is Detect and name == "forward":
        return Detect.forward
    raise ValueError("Unsupported attribute in the face checkpoint")


LEGACY_FACE_GLOBALS = [
    PoseModel,
    (IterableSimpleNamespace, "ultralytics.yolo.utils.IterableSimpleNamespace"),
    (_legacy_detect_forward, "builtins.getattr"),
    *((cls, f"ultralytics.nn.modules.{cls.__name__}")
      for cls in (Bottleneck, C2f, Concat, Conv, Detect, DFL, Pose, SPPF)),
]


def load_yolo(weights: Path, *, face: bool = False) -> YOLO:
    safe_globals = getattr(torch.serialization, "safe_globals", None)
    classes = CHECKPOINT_CLASSES + LEGACY_FACE_GLOBALS if face else CHECKPOINT_CLASSES
    with safe_globals(classes) if safe_globals else nullcontext():
        return YOLO(str(weights))
