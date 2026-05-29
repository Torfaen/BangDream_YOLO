"""Tests for centralized config loading."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bangdream_yolo.config import DEFAULT_ADB_SERIAL, DEFAULT_MUMU_PATH, load_config, project_root


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_existing_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.yml"
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(missing)

        self.assertEqual(config.mumu_path, DEFAULT_MUMU_PATH)
        self.assertEqual(config.adb_serial, DEFAULT_ADB_SERIAL)
        self.assertEqual(config.model_path, project_root() / "models/bangdream_yolo_m4_green_bar.pt")
        self.assertEqual(config.calibration_path, project_root() / "data/calibration.yml")
        self.assertFalse(config.enable_touch)

    def test_reads_config_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        'mumu_path: "D:\\\\MuMu"',
                        'adb_serial: "127.0.0.1:7555"',
                        "instance_id: 2",
                        "display_id: 1",
                        'model_path: "models/custom.pt"',
                        'calibration_path: "data/custom.yml"',
                        "enable_touch: true",
                        "topmost: true",
                        "conf: 0.5",
                        "asset_abi: x86_64",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = load_config(config_path)

        self.assertEqual(config.mumu_path, Path(r"D:\MuMu"))
        self.assertEqual(config.adb_serial, "127.0.0.1:7555")
        self.assertEqual(config.instance_id, 2)
        self.assertEqual(config.display_id, 1)
        self.assertEqual(config.model_path, project_root() / "models/custom.pt")
        self.assertEqual(config.calibration_path, project_root() / "data/custom.yml")
        self.assertTrue(config.enable_touch)
        self.assertTrue(config.topmost)
        self.assertEqual(config.conf, 0.5)
        self.assertEqual(config.asset_abi, "x86_64")

    def test_environment_overrides_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yml"
            config_path.write_text(
                'adb_serial: "emulator-5554"\nenable_touch: false\n',
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "BANGDREAM_ADB_SERIAL": "override-serial",
                    "BANGDREAM_ENABLE_TOUCH": "1",
                },
                clear=True,
            ):
                config = load_config(config_path)

        self.assertEqual(config.adb_serial, "override-serial")
        self.assertTrue(config.enable_touch)


if __name__ == "__main__":
    unittest.main()
