import os
import sys
import types
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "dotenv" not in sys.modules:
    mock_dotenv = types.ModuleType("dotenv")

    def _load_dotenv(*args, **kwargs):  # pragma: no cover - simple shim
        return None

    setattr(mock_dotenv, "load_dotenv", _load_dotenv)  # type: ignore[attr-defined]
    sys.modules["dotenv"] = mock_dotenv

from app import COLLECTION_ITEM_TYPES, app, item_tags  # noqa: E402


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
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            exclude_types=None,
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
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            exclude_types=None,
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


class ApiItemsCollectionExclusionTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_excludes_collections_when_flagged(self):
        captured = {}

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            exclude_types=None,
        ):
            captured.setdefault("exclude_types", exclude_types)
            return {
                "Items": [
                    {
                        "Id": "1",
                        "Type": "Movie",
                        "Name": "Movie Example",
                        "Path": "/movie.mkv",
                        "Tags": [],
                    },
                    {
                        "Id": "2",
                        "Type": "BoxSet",
                        "Name": "Collection Example",
                        "Path": None,
                        "Tags": [],
                    },
                ],
                "TotalRecordCount": 2,
            }

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie", "Series"],
                    "excludeCollections": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data.get("Items", [])), 1)
        self.assertTrue(all(item["Type"] != "BoxSet" for item in data.get("Items", [])))
        self.assertEqual(
            set(captured.get("exclude_types") or ()), set(COLLECTION_ITEM_TYPES)
        )


class ApiExportCollectionExclusionTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_export_omits_collections_when_flagged(self):
        captured = []

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            exclude_types=None,
        ):
            captured.append(exclude_types)
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "1",
                            "Name": "Movie Example",
                            "Path": "/movie.mkv",
                            "ProviderIds": {},
                            "Type": "Movie",
                            "TagItems": [],
                            "Tags": [],
                        },
                        {
                            "Id": "2",
                            "Name": "Collection Example",
                            "Path": None,
                            "ProviderIds": {},
                            "Type": "BoxSet",
                            "TagItems": [],
                            "Tags": [],
                        },
                    ],
                    "TotalRecordCount": 2,
                }
            return {"Items": [], "TotalRecordCount": 2}

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/export",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie", "Series"],
                    "excludeCollections": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        csv_output = response.data.decode("utf-8")
        self.assertIn("Movie Example", csv_output)
        self.assertNotIn("Collection Example", csv_output)
        self.assertTrue(
            any(set(types or ()) == set(COLLECTION_ITEM_TYPES) for types in captured)
        )


class ApiTagsAggregatedFallbackTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_aggregated_fallback_uses_tags_property(self):
        captured_fields = []

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            exclude_types=None,
        ):
            captured_fields.append(fields)
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "1",
                            "Tags": ["Alpha", "beta"],
                        }
                    ],
                    "TotalRecordCount": 1,
                }
            return {"Items": [], "TotalRecordCount": 1}

        with patch("app.jf_get", side_effect=RuntimeError("boom")):
            with patch("app.page_items", side_effect=fake_page_items):
                response = self.client.post(
                    "/api/tags",
                    json={
                        "base": "http://example.com",
                        "apiKey": "dummy",
                        "libraryId": "lib",
                        "userId": "user",
                        "types": ["Movie"],
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        data = response.get_json()
        self.assertEqual(data.get("source"), "aggregated")
        self.assertEqual(data.get("tags"), ["Alpha", "beta"])
        self.assertTrue(any("Tags" in fields for fields in captured_fields))


class IndexConfigRenderTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_renders_environment_configuration(self):
        base_url = "http://configured.example"
        api_key = "configured-key"

        with patch.dict(
            os.environ,
            {"JELLYFIN_BASE_URL": base_url, "JELLYFIN_API_KEY": api_key},
        ):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn(base_url, html)
        self.assertIn(api_key, html)


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


class ApiApplyUserScopedTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_user_scoped_endpoint_invoked_when_user_id_provided(self):
        calls = []

        def fake_jf_post(url, api_key, params=None, timeout=30):
            calls.append((url, params))
            return {}

        payload = {
            "base": "http://example.com",
            "apiKey": "dummy",
            "userId": "user123",
            "changes": [
                {"id": "item1", "add": ["NewTag"], "remove": []},
            ],
        }

        with patch("app.jf_post", side_effect=fake_jf_post):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                (
                    "http://example.com/Users/user123/Items/item1/Tags",
                    {"AddTags": "NewTag"},
                )
            ],
        )

    def test_falls_back_to_global_endpoint_when_user_scope_fails(self):
        calls = []

        class Boom(Exception):
            pass

        def fake_jf_post(url, api_key, params=None, timeout=30):
            calls.append((url, params))
            if len(calls) == 1:
                raise Boom("user endpoint down")
            return {}

        payload = {
            "base": "http://example.com",
            "apiKey": "dummy",
            "userId": "user123",
            "changes": [
                {"id": "item42", "add": ["TagA"], "remove": []},
            ],
        }

        with patch("app.jf_post", side_effect=fake_jf_post):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                (
                    "http://example.com/Users/user123/Items/item42/Tags",
                    {"AddTags": "TagA"},
                ),
                ("http://example.com/Items/item42/Tags", {"AddTags": "TagA"}),
            ],
        )
        data = response.get_json()
        self.assertTrue(response.is_json)
        updated = data.get("updated", [])[0]
        self.assertEqual(updated.get("added"), ["TagA"])
        self.assertEqual(updated.get("errors"), [])


if __name__ == "__main__":
    unittest.main()
