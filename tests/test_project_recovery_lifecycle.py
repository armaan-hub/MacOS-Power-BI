"""Controller lifecycle checks for opening and saving a recovered project."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.project import load_project, new_project, save_project


class ProjectRecoveryLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Project recovery tests"])

    def test_controller_opens_backup_and_saves_without_rotating_corrupt_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "recovery.npa"
            backup_path = Path(f"{project_path}.bak")
            save_project(project_path, new_project("Last good"))
            save_project(project_path, new_project("Current"))
            project_path.write_text("{corrupt primary", encoding="utf-8")

            controller = StudioController(
                self.app,
                QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
            )
            with (
                patch.object(controller, "_confirm_replace_project", return_value=True),
                patch("analytics_studio.controller.QMessageBox.warning"),
            ):
                self.assertTrue(controller.open_project_path(project_path))

            self.assertEqual(controller.projectName, "Last good")
            self.assertTrue(controller._recovered_from_backup)
            self.assertTrue(controller._save_to(project_path))
            self.assertFalse(controller._recovered_from_backup)

            primary, recovered_primary = load_project(project_path)
            backup, recovered_backup = load_project(backup_path)
            self.assertFalse(recovered_primary)
            self.assertFalse(recovered_backup)
            self.assertEqual(primary["name"], "Last good")
            self.assertEqual(backup["name"], "Last good")


if __name__ == "__main__":
    unittest.main()
