import tempfile
import unittest
from pathlib import Path

from webapp.api import ApiError
from webapp.services.model_catalog import (
    list_stage1_models,
    list_stage2_models,
    resolve_stage1,
    resolve_stage2,
)


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        # 临时目录构造与真实结构一致的 stage1/face、stage1/head、stage2
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.face_dir = root / "stage1" / "face"
        self.head_dir = root / "stage1" / "head"
        self.stage2_dir = root / "stage2"
        for directory in (self.face_dir, self.head_dir, self.stage2_dir):
            directory.mkdir(parents=True)
        # 放置权重，并各放一个应被忽略的非 .pt 文件
        (self.face_dir / "a-face.pt").touch()
        (self.head_dir / "b-head.pt").touch()
        (self.stage2_dir / "c-smoke.pt").touch()
        (self.stage2_dir / "ignore.txt").touch()
        self.config = {
            "FACE_DIR": self.face_dir,
            "HEAD_DIR": self.head_dir,
            "STAGE2_DIR": self.stage2_dir,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_stage1_grouped_by_kind(self):
        self.assertEqual(list_stage1_models(self.config), [
            {"kind": "face", "file": "a-face.pt", "value": "face/a-face.pt"},
            {"kind": "head", "file": "b-head.pt", "value": "head/b-head.pt"},
        ])

    def test_lists_stage2_pt_only(self):
        self.assertEqual(list_stage2_models(self.config),
                         [{"file": "c-smoke.pt", "value": "c-smoke.pt"}])

    def test_resolve_stage1_returns_kind_and_absolute_path(self):
        kind, path = resolve_stage1("head/b-head.pt", self.config)
        self.assertEqual(kind, "head")
        self.assertEqual(Path(path), (self.head_dir / "b-head.pt").resolve())

    def test_resolve_stage2_returns_absolute_path(self):
        path = resolve_stage2("c-smoke.pt", self.config)
        self.assertEqual(Path(path), (self.stage2_dir / "c-smoke.pt").resolve())

    def test_rejects_unknown_and_traversal_choices(self):
        for bad in ("face/missing.pt", "../a-face.pt", "face/../head/b-head.pt", "x/y.pt", 1, None):
            with self.assertRaises(ApiError):
                resolve_stage1(bad, self.config)
        for bad in ("missing.pt", "../c-smoke.pt", 5):
            with self.assertRaises(ApiError):
                resolve_stage2(bad, self.config)

    def test_missing_directory_returns_empty_list(self):
        empty_config = {
            "FACE_DIR": Path(self.tmp.name) / "nope1",
            "HEAD_DIR": Path(self.tmp.name) / "nope2",
            "STAGE2_DIR": Path(self.tmp.name) / "nope3",
        }
        self.assertEqual(list_stage1_models(empty_config), [])
        self.assertEqual(list_stage2_models(empty_config), [])


if __name__ == "__main__":
    unittest.main()
