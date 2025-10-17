import os
import sys
import types
import unittest
from unittest.mock import patch

if "dotenv" not in sys.modules:
    mock_dotenv = types.ModuleType("dotenv")

    def _load_dotenv(*args, **kwargs):  # pragma: no cover - simple shim
        return None

    setattr(mock_dotenv, "load_dotenv", _load_dotenv)  # type: ignore[attr-defined]
    sys.modules["dotenv"] = mock_dotenv

from app import app, item_tags


class ItemTagsTest(unittest.TestCase):
    def test_merges_tagitems_and_tags(self):
        item = {
            "TagItems": [{"Name": "Sci-Fi"}, {"Name": "Drama"}, {"Name": "sci-fi"}],
            "Tags": ["Drama", "Comedy", ""],
        }

        self.assertEqual(item_tags(item), ["Sci-Fi", "Drama", "Comedy"])

    def test_handles_missing_sections(self):
        self.assertEqual(item_tags({"TagItems": None, "Tags": None}), [])
        self.assertEqual(item_tags({"Tags": ["Only"]}), ["Only"])
        self.assertEqual(item_tags({"TagItems": [{"Name": "Only"}]}), ["Only"])


class ApiItemsFieldsTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_api_items_requests_tags_field(self):
        captured = {}

        def fake_page_items(
            base, api_key, user_id, lib_id, include_types, fields, start, limit
        ):
            captured["fields"] = fields
            return {"Items": [], "TotalRecordCount": 0}

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Tags", captured["fields"])


class ApiExportFieldsTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_api_export_requests_tags_field_and_merges(self):
        captured_fields = []

        def fake_page_items(
            base, api_key, user_id, lib_id, include_types, fields, start, limit
        ):
            captured_fields.append(fields)
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "1",
                            "Name": "Example",
                            "Path": "/file.mkv",
                            "ProviderIds": {},
                            "Type": "Movie",
                            "TagItems": [{"Name": "Sci-Fi"}],
                            "Tags": ["Drama"],
                        }
                    ],
                    "TotalRecordCount": 1,
                }
            return {"Items": [], "TotalRecordCount": 1}

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/export",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Tags" in fields for fields in captured_fields))
        csv_output = response.data.decode("utf-8")
        self.assertIn("Drama;Sci-Fi", csv_output)


class ApiBaseValidationTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_missing_base_returns_400(self):
        with patch.dict(
            os.environ,
            {"JELLYFIN_BASE_URL": "", "JELLYFIN_API_KEY": ""},
        ):
            endpoints = {
                "/api/users": {"base": "   ", "apiKey": "dummy"},
                "/api/libraries": {"base": "", "apiKey": "dummy"},
                "/api/tags": {
                    "base": " ",
                    "apiKey": "dummy",
                    "libraryId": "lib",
                },
                "/api/items": {
                    "base": "\t",
                    "apiKey": "dummy",
                    "libraryId": "lib",
                    "userId": "user",
                },
                "/api/export": {
                    "base": "\n",
                    "apiKey": "dummy",
                    "libraryId": "lib",
                    "userId": "user",
                },
                "/api/apply": {"base": " ", "apiKey": "dummy", "changes": []},
            }

            for path, payload in endpoints.items():
                with self.subTest(path=path):
                    response = self.client.post(path, json=payload)
                    self.assertEqual(response.status_code, 400)
                    self.assertTrue(response.is_json)
                    self.assertEqual(
                        response.get_json(),
                        {"error": "Jellyfin base URL is required"},
                    )


class ApiConfigFallbackTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_uses_environment_defaults_when_payload_missing(self):
        captured = {}

        def fake_jf_get(url, api_key, params=None, timeout=30):
            captured["url"] = url
            captured["api_key"] = api_key
            return []

        with patch.dict(
            os.environ,
            {
                "JELLYFIN_BASE_URL": "http://env.example",
                "JELLYFIN_API_KEY": "env-key",
            },
        ):
            with patch("app.jf_get", side_effect=fake_jf_get):
                response = self.client.post("/api/users", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["url"], "http://env.example/Users")
        self.assertEqual(captured["api_key"], "env-key")


if __name__ == "__main__":
    unittest.main()
