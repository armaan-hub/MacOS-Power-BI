"""Acceptance checks for anonymous OData Feed discovery and saved-source lifecycle."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate
from analytics_studio.odata import (
    ODataError,
    list_odata_entity_sets,
    read_odata_entity_set,
)
from analytics_studio.odata_dialog import ODataFeedImportDialog
from analytics_studio.project import load_project


ROOT = "https://api.example.test/odata/"
OPTIONS = {
    "entity_set_name": "Metrics",
    "entity_url": f"{ROOT}Metrics",
}


class ODataImportLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def candidate(value: str) -> ImportCandidate:
        return ImportCandidate(
            "odata",
            ["id", "amount"],
            [{"id": "1", "amount": value}],
            dict(OPTIONS),
            [],
        )

    def test_discovery_pagination_flat_values_and_same_origin_rules(self) -> None:
        service_document = {
            "value": [
                {"name": "Metrics", "kind": "EntitySet", "url": "Metrics"},
                {"name": "Products", "kind": "EntitySet", "url": "Products"},
                {"name": "Service", "kind": "FunctionImport", "url": "Service"},
            ]
        }
        with patch(
            "analytics_studio.odata._read_json",
            return_value=(service_document, ROOT, 120),
        ) as read_json:
            entity_sets = list_odata_entity_sets("https://api.example.test/odata")

        self.assertEqual([item["entity_set_name"] for item in entity_sets], ["Metrics", "Products"])
        self.assertEqual(read_json.call_args.args, (ROOT, ROOT))

        page_one = {
            "value": [
                {"id": 1, "amount": Decimal("10.50"), "active": True, "note": None,
                 "@odata.type": "#Analytics.Metric"}
            ],
            "@odata.nextLink": f"{ROOT}Metrics?$skiptoken=next",
        }
        page_two = {
            "value": [{"id": 2, "amount": Decimal("20.25"), "active": False}]
        }
        pages = {
            OPTIONS["entity_url"]: page_one,
            f"{OPTIONS['entity_url']}?$skiptoken=next": page_two,
        }
        requested: list[str] = []

        def read_page(url: str, same_origin_as: str):
            requested.append(url)
            return pages[url], url, 80

        with patch("analytics_studio.odata._read_json", side_effect=read_page):
            result = read_odata_entity_set(
                {"service_root": ROOT}, OPTIONS
            )

        self.assertEqual(requested, list(pages))
        self.assertEqual(result.headers, ["id", "amount", "active", "note"])
        self.assertEqual(result.rows, [
            {"id": "1", "amount": "10.50", "active": "TRUE", "note": ""},
            {"id": "2", "amount": "20.25", "active": "FALSE", "note": ""},
        ])

        with patch(
            "analytics_studio.odata._read_json",
            return_value=({"value": [{"name": "Bad", "url": "https://other.test/Bad"}]}, ROOT, 20),
        ):
            with self.assertRaisesRegex(ODataError, "outside its HTTPS origin"):
                list_odata_entity_sets(ROOT)

    def test_dialog_discovers_previews_and_imports_the_selected_entity_set(self) -> None:
        dialog = ODataFeedImportDialog()
        dialog.service_root_edit.setText("https://api.example.test/odata")
        entity_sets = [
            {"entity_set_name": "Metrics", "entity_url": OPTIONS["entity_url"]},
            {"entity_set_name": "Products", "entity_url": f"{ROOT}Products"},
        ]
        reads = []

        def read_entity(connection, options, *, row_limit=100_000):
            reads.append((dict(connection), dict(options), row_limit))
            name = options["entity_set_name"]
            return ImportCandidate("odata", ["id"], [{"id": name}], dict(options), [])

        with (
            patch("analytics_studio.odata_dialog.list_odata_entity_sets", return_value=entity_sets),
            patch("analytics_studio.odata_dialog.read_odata_entity_set", side_effect=read_entity),
        ):
            dialog._connect()
            self.assertEqual(dialog.entity_set_combo.count(), 2)
            dialog.entity_set_combo.setCurrentIndex(1)
            self.assertEqual(dialog.preview_model.data(dialog.preview_model.index(0, 0)), "Products")
            dialog._accept_import()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.service_root, ROOT)
        self.assertEqual(dialog.candidate.options["entity_set_name"], "Products")
        self.assertEqual(len(reads), 3)
        self.assertEqual(reads[0][2], 100)
        self.assertEqual(reads[-1][2], 100_000)
        dialog.deleteLater()

    def test_pathless_source_reopens_and_refreshes_selected_entity_set(self) -> None:
        controller = self.controller("settings.ini")
        first = self.candidate("10")
        self.assertTrue(controller._commit_odata_import({"service_root": ROOT}, first))
        source_id = controller.activeTableId

        project_path = self.root / "odata-project.npa"
        self.assertTrue(controller._save_to(project_path))
        saved_project, _ = load_project(project_path)
        saved_source = saved_project["data_sources"][0]
        self.assertEqual(saved_source["connection"], {"service_root": ROOT})
        self.assertEqual(saved_source["parser_options"], OPTIONS)

        reopened = self.controller("reopened-settings.ini")
        changed = self.candidate("20")
        with patch(
            "analytics_studio.controller.read_odata_entity_set",
            side_effect=[changed, self.candidate("30")],
        ) as read_entity:
            self.assertTrue(reopened.open_project_path(project_path))
            self.assertEqual(reopened._rows, [{"id": "1", "amount": "20"}])
            reopened.refresh_source()

        self.assertEqual(reopened._active_source_id, source_id)
        self.assertEqual(reopened._rows, [{"id": "1", "amount": "30"}])
        self.assertEqual(read_entity.call_count, 2)
        self.assertEqual(read_entity.call_args_list[0].args, ({"service_root": ROOT}, OPTIONS))


if __name__ == "__main__":
    unittest.main()
