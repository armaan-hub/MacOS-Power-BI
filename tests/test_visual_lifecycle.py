import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController


class VisualLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def controller(self) -> StudioController:
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_visual_lifecycle(self):
        controller = self.controller()
        initial_visuals = controller.activeVisualObjects
        
        # Add visual
        v_id = controller.add_visual("line", "Trends", 100, 200, 500, 400)
        
        visuals = controller.activeVisualObjects
        added = next((v for v in visuals if v["id"] == v_id), None)
        self.assertIsNotNone(added)
        self.assertEqual(added["type"], "line")
        self.assertEqual(added["title"], "Trends")
        self.assertEqual(added["x"], 100)
        self.assertEqual(added["y"], 200)
        self.assertEqual(added["width"], 500)
        self.assertEqual(added["height"], 400)
        
        # Move visual
        controller.move_visual(v_id, 150, 250)
        visuals = controller.activeVisualObjects
        moved = next((v for v in visuals if v["id"] == v_id), None)
        self.assertEqual(moved["x"], 150)
        self.assertEqual(moved["y"], 250)
        
        # Resize visual
        controller.resize_visual(v_id, 600, 450)
        visuals = controller.activeVisualObjects
        resized = next((v for v in visuals if v["id"] == v_id), None)
        self.assertEqual(resized["width"], 600)
        self.assertEqual(resized["height"], 450)
        
        # Save and reopen
        project_path = self.root / "visuals.npa"
        self.assertTrue(controller._save_to(project_path))
        
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        
        visuals_reopened = reopened.activeVisualObjects
        reopened_visual = next((v for v in visuals_reopened if v["id"] == v_id), None)
        self.assertIsNotNone(reopened_visual)
        self.assertEqual(reopened_visual["x"], 150)
        self.assertEqual(reopened_visual["width"], 600)
        
        # Remove visual
        reopened.remove_visual(v_id)
        visuals_final = reopened.activeVisualObjects
        removed = next((v for v in visuals_final if v["id"] == v_id), None)
        self.assertIsNone(removed)

if __name__ == "__main__":
    unittest.main()
