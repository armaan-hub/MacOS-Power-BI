import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController


class ReportPagesLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def controller(self) -> StudioController:
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_page_management_lifecycle(self):
        controller = self.controller()
        
        # Start with 1 page
        self.assertEqual(len(controller.pages), 1)
        page1_id = controller.pages[0]["id"]
        self.assertEqual(controller.pages[0]["name"], "Overview")
        self.assertFalse(controller.pages[0]["hidden"])
        
        # Add Page
        controller.add_page()
        self.assertEqual(len(controller.pages), 2)
        page2_id = controller.pages[1]["id"]
        self.assertEqual(controller._active_page_id, page2_id)
        
        # Rename Page
        controller.rename_page(page2_id, "Dashboard Main")
        self.assertEqual(controller.pages[1]["name"], "Dashboard Main")
        
        # Hide Page
        controller.hide_page(page2_id, True)
        self.assertTrue(controller.pages[1]["hidden"])
        
        # Duplicate Page
        controller.duplicate_page(page1_id)
        self.assertEqual(len(controller.pages), 3)
        # Should be inserted after page1. index 1
        page1_copy = controller.pages[1]
        self.assertEqual(page1_copy["name"], "Overview (Copy)")
        copy_id = page1_copy["id"]
        
        # Reorder Page
        # current pages: [Page 1, Page 1 (Copy), Dashboard Main]
        # move Dashboard Main (idx 2) to 0
        controller.reorder_page(page2_id, 0)
        self.assertEqual(controller.pages[0]["id"], page2_id)
        self.assertEqual(controller.pages[1]["id"], page1_id)
        
        # Delete Page
        # remove Page 1 (Copy) -> idx 2 now
        controller.delete_page(copy_id)
        self.assertEqual(len(controller.pages), 2)
        self.assertEqual(controller.pages[0]["id"], page2_id)
        self.assertEqual(controller.pages[1]["id"], page1_id)
        
        # Save and reopen
        project_path = self.root / "pages.npa"
        self.assertTrue(controller._save_to(project_path))
        
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        
        self.assertEqual(len(reopened.pages), 2)
        self.assertEqual(reopened.pages[0]["id"], page2_id)
        self.assertEqual(reopened.pages[0]["name"], "Dashboard Main")
        self.assertTrue(reopened.pages[0]["hidden"])
        
        self.assertEqual(reopened.pages[1]["id"], page1_id)
        self.assertEqual(reopened.pages[1]["name"], "Overview")

    def test_delete_last_page_ignored(self):
        controller = self.controller()
        page_id = controller.pages[0]["id"]
        controller.delete_page(page_id)
        self.assertEqual(len(controller.pages), 1)

if __name__ == "__main__":
    unittest.main()
