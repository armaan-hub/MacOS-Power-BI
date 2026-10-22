"""Acceptance checks for anonymous OData Feed discovery and saved-source lifecycle."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from urllib.error import URLError
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio import odata
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

    @staticmethod
    def _page(document, response_bytes=10, url=OPTIONS["entity_url"]):
        return document, url, response_bytes

    @staticmethod
    def _run_page(document, *, row_limit=100_000, response_bytes=10):
        with patch(
            "analytics_studio.odata._read_json",
            return_value=ODataImportLifecycleTests._page(document, response_bytes),
        ):
            return read_odata_entity_set(
                {"service_root": ROOT}, OPTIONS, row_limit=row_limit
            )

    def test_entity_reader_rejects_malformed_empty_nonobject_and_nested_results(self) -> None:
        cases = [
            ({"value": "not-an-array"}, "does not contain an entity list"),
            ({"value": []}, "returned no rows"),
            ({"value": ["not-an-object"]}, "non-object row"),
            ({"value": [{"id": {"nested": 1}}]}, "is nested"),
        ]
        for document, message in cases:
            with self.subTest(document=document):
                with self.assertRaisesRegex(ODataError, message):
                    self._run_page(document)

    def test_entity_reader_enforces_page_row_column_cell_and_text_limits(self) -> None:
        with patch.object(odata, "MAX_TOTAL_RESPONSE_BYTES", 3):
            first = {"value": [{"id": 1}], "@odata.nextLink": "?skip=1"}
            second = {"value": [{"id": 2}]}
            with patch(
                "analytics_studio.odata._read_json",
                side_effect=[
                    (first, OPTIONS["entity_url"], 2),
                    (second, OPTIONS["entity_url"] + "?skip=1", 2),
                ],
            ):
                with self.assertRaisesRegex(ODataError, "100 MiB response limit"):
                    read_odata_entity_set({"service_root": ROOT}, OPTIONS)

        with patch.object(odata, "MAX_PAGE_COUNT", 1):
            with patch(
                "analytics_studio.odata._read_json",
                return_value=(
                    {"value": [{"id": 1}], "@odata.nextLink": "?skip=1"},
                    OPTIONS["entity_url"], 1,
                ),
            ):
                with self.assertRaisesRegex(ODataError, "1-page limit"):
                    read_odata_entity_set({"service_root": ROOT}, OPTIONS)

        with patch.object(odata, "MAX_COLUMNS", 1):
            with self.assertRaisesRegex(ODataError, "more than 1 columns"):
                self._run_page({"value": [{"a": 1, "b": 2}]})

        with patch.object(odata, "MAX_CELL_BYTES", 2):
            with self.assertRaisesRegex(ODataError, "1 MiB per-cell"):
                self._run_page({"value": [{"id": "abc"}]})

        with patch.object(odata, "MAX_SQLITE_TEXT_BYTES", 3):
            with self.assertRaisesRegex(ODataError, "80 MiB rendered text limit"):
                self._run_page({"value": [{"id": "four"}]})

        limited = self._run_page(
            {"value": [{"id": 1}, {"id": 2}, {"id": 3}]}, row_limit=1
        )
        self.assertEqual(limited.rows, [{"id": 1}])
        self.assertTrue(any("Preview is limited to 1 rows" in item for item in limited.notices))

        with patch.object(odata, "MAX_CELLS", 2):
            limited = self._run_page({"value": [{"id": 1}, {"id": 2}, {"id": 3}]})
        self.assertEqual(limited.rows, [{"id": 1}, {"id": 2}])
        self.assertTrue(any("capped at 2 rows" in item for item in limited.notices))

    def test_json_reader_enforces_response_size_malformed_json_timeout_and_tls(self) -> None:
        class Response:
            headers = {}

            def __init__(self, body, url=OPTIONS["entity_url"]):
                self.body = body
                self.url = url

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self, limit):
                self.read_limit = limit
                return self.body[:limit]

            def geturl(self):
                return self.url

        class Opener:
            def __init__(self, response=None, error=None):
                self.response = response
                self.error = error
                self.timeout = None

            def open(self, request, timeout):
                self.timeout = timeout
                if self.error:
                    raise self.error
                return self.response

        with patch.object(odata, "MAX_RESPONSE_BYTES", 3):
            opener = Opener(Response(b'{"value": []}'))
            with patch("analytics_studio.odata.build_opener", return_value=opener):
                with self.assertRaisesRegex(ODataError, "10 MiB per-response"):
                    odata._read_json(OPTIONS["entity_url"], ROOT)
            self.assertEqual(opener.response.read_limit, 4)

        for body, message in ((b"{bad", "invalid UTF-8 JSON"), (b"[]", "must be a JSON object")):
            opener = Opener(Response(body))
            with self.subTest(body=body), patch(
                "analytics_studio.odata.build_opener", return_value=opener
            ):
                with self.assertRaisesRegex(ODataError, message):
                    odata._read_json(OPTIONS["entity_url"], ROOT)

        for error in (
            TimeoutError("timed out"),
            URLError(ssl.SSLCertVerificationError("untrusted certificate")),
        ):
            opener = Opener(error=error)
            with self.subTest(error=type(error).__name__), patch(
                "analytics_studio.odata.build_opener", return_value=opener
            ):
                with self.assertRaisesRegex(ODataError, "Could not reach the OData service"):
                    odata._read_json(OPTIONS["entity_url"], ROOT)
            self.assertEqual(opener.timeout, odata.REQUEST_TIMEOUT_SECONDS)

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
            {"id": 1, "amount": Decimal("10.50"), "active": True, "note": None},
            {"id": 2, "amount": Decimal("20.25"), "active": False, "note": None},
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
