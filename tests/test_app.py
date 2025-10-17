import os
import sys
import types
import unittest
from unittest.mock import patch

import requests  # type: ignore[import-untyped]

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if "dotenv" not in sys.modules:
    mock_dotenv = types.ModuleType("dotenv")

    def _load_dotenv(*args, **kwargs):  # pragma: no cover - simple shim
        return None

    setattr(mock_dotenv, "load_dotenv", _load_dotenv)  # type: ignore[attr-defined]
    sys.modules["dotenv"] = mock_dotenv

import app as app_module  # noqa: E402
from app import COLLECTION_ITEM_TYPES, app, item_tags  # noqa: E402


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, http_error=None):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {"content-type": "application/json"}
        self.text = "" if json_data is None else "body"
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise self._http_error
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def json(self):
        return self._json_data if self._json_data is not None else {}


class JfUpdateTagsEndpointTest(unittest.TestCase):
    def test_puts_filtered_payload_and_preserves_supported_fields(self):
        base = "http://example.com"
        api_key = "token"
        item_id = "12345"
        user_id = "user"
        item_payload = {
            "Id": item_id,
            "Name": "Example",
            "SortName": "Example",
            "Overview": "",
            "Genres": ["Drama"],
            "Tags": ["Legacy"],
            "TagItems": [{"Name": "Existing"}],
            "ImageTags": {"Primary": "abc"},
            "People": [{"Name": "Actor"}],
            "Studios": [{"Name": "Studio"}],
            "ProviderIds": {"Imdb": "tt123"},
        }

        with patch("app.jf_get", return_value=item_payload) as mock_get, patch(
            "app.requests.put", return_value=DummyResponse()
        ) as mock_put, patch("app.jf_post") as mock_post:
            mock_post.return_value = {}
            result = app_module.jf_update_tags(
                base,
                api_key,
                item_id,
                add=["New"],
                remove=["Legacy"],
                user_id=user_id,
            )

        self.assertEqual(result, ["Existing", "New"])
        mock_get.assert_called_once_with(
            f"{base}/Users/{user_id}/Items/{item_id}", api_key
        )
        mock_put.assert_called_once()
        put_kwargs = mock_put.call_args.kwargs
        self.assertEqual(put_kwargs["json"]["Id"], item_id)
        self.assertEqual(put_kwargs["json"]["Tags"], ["Existing", "New"])
        self.assertEqual(put_kwargs["json"]["People"], item_payload["People"])
        self.assertEqual(put_kwargs["json"]["Studios"], item_payload["Studios"])
        self.assertNotIn("TagItems", put_kwargs["json"])
        self.assertNotIn("ImageTags", put_kwargs["json"])
        self.assertNotIn("Overview", put_kwargs["json"])
        mock_post.assert_not_called()

    def test_put_falls_back_to_post_when_unsupported(self):
        base = "http://example.com"
        api_key = "token"
        item_id = "12345"
        error_response = DummyResponse(status_code=405)
        unsupported_error = requests.HTTPError("Method Not Allowed")
        unsupported_error.response = error_response
        error_response._http_error = unsupported_error

        with patch(
            "app.jf_get", return_value={"Id": item_id, "Tags": [], "TagItems": []}
        ) as mock_get, patch(
            "app.requests.put", return_value=error_response
        ) as mock_put, patch(
            "app.jf_post", return_value={}
        ) as mock_post:
            result = app_module.jf_update_tags(
                base,
                api_key,
                item_id,
                add=["New"],
                remove=[],
            )

        self.assertEqual(result, ["New"])
        mock_get.assert_called_once_with(f"{base}/Items/{item_id}", api_key)
        mock_put.assert_called_once()
        mock_post.assert_called_once()
        put_payload = mock_put.call_args.kwargs["json"]
        post_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(put_payload, post_payload)
        self.assertEqual(post_payload["Id"], item_id)
        self.assertEqual(post_payload["Tags"], ["New"])


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

    def test_api_items_clamps_limit_to_100(self):
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
            captured["limit"] = limit
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
                    "limit": 250,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["limit"], 100)

    def test_api_items_collects_matches_across_pages(self):
        starts = []

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
            starts.append(start)
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "first",
                            "Type": "Movie",
                            "Name": "First",
                            "Path": "/first.mkv",
                            "Tags": ["Other"],
                        }
                    ],
                    "TotalRecordCount": 2,
                }
            if start == 1:
                return {
                    "Items": [
                        {
                            "Id": "match",
                            "Type": "Movie",
                            "Name": "Match",
                            "Path": "/match.mkv",
                            "Tags": ["Match"],
                        }
                    ],
                    "TotalRecordCount": 2,
                }
            return {"Items": [], "TotalRecordCount": 2}

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Match",
                    "limit": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreaterEqual(len(starts), 2)
        self.assertEqual(data["TotalMatchCount"], 1)
        self.assertEqual(data["ReturnedCount"], 1)
        self.assertEqual(len(data["Items"]), 1)
        self.assertEqual(data["Items"][0]["Id"], "match")

    def test_api_items_limits_results_after_offset(self):
        starts = []
        records = [
            {
                "Id": "other-1",
                "Type": "Movie",
                "Name": "Other 1",
                "Path": "/other-1.mkv",
                "Tags": ["Other"],
            },
            {
                "Id": "match-1",
                "Type": "Movie",
                "Name": "Match 1",
                "Path": "/match-1.mkv",
                "Tags": ["Match"],
            },
            {
                "Id": "match-2",
                "Type": "Movie",
                "Name": "Match 2",
                "Path": "/match-2.mkv",
                "Tags": ["Match"],
            },
            {
                "Id": "match-3",
                "Type": "Movie",
                "Name": "Match 3",
                "Path": "/match-3.mkv",
                "Tags": ["Match"],
            },
            {
                "Id": "match-4",
                "Type": "Movie",
                "Name": "Match 4",
                "Path": "/match-4.mkv",
                "Tags": ["Match"],
            },
        ]

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
            starts.append((start, limit))
            slice_end = start + limit
            return {
                "Items": records[start:slice_end],
                "TotalRecordCount": len(records),
            }

        with patch("app.page_items", side_effect=fake_page_items):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Match",
                    "startIndex": 1,
                    "limit": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreaterEqual(len(starts), 3)
        self.assertEqual(data["TotalMatchCount"], 4)
        self.assertEqual(data["ReturnedCount"], 2)
        self.assertEqual(len(data["Items"]), 2)
        self.assertEqual([item["Id"] for item in data["Items"]], ["match-2", "match-3"])


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


class JfUpdateTagsHelperTest(unittest.TestCase):
    def test_posts_merged_tags_to_item_endpoint(self):
        captured = {}

        def fake_jf_get(url, api_key, params=None, timeout=30):
            self.assertEqual(url, "http://example.com/Items/item1")
            return {
                "Id": "item1",
                "Name": "Example",
                "TagItems": [{"Name": "Sci-Fi"}],
                "Tags": ["Drama"],
                "ProviderIds": {"Imdb": "tt123"},
            }

        def fake_put(url, api_key, json=None, timeout=30):
            captured["url"] = url
            captured["json"] = json
            return {}

        with patch("app.jf_get", side_effect=fake_jf_get):
            with patch("app.jf_put_with_fallback", side_effect=fake_put):
                final_tags = app_module.jf_update_tags(
                    "http://example.com", "dummy", "item1", ["Comedy"], ["Drama"]
                )

        self.assertEqual(final_tags, ["Comedy", "Sci-Fi"])
        self.assertEqual(captured["url"], "http://example.com/Items/item1")
        self.assertEqual(
            captured["json"],
            {
                "Id": "item1",
                "Tags": ["Comedy", "Sci-Fi"],
                "Name": "Example",
                "ProviderIds": {"Imdb": "tt123"},
            },
        )

    def test_fetches_user_scoped_endpoint_when_user_id_provided(self):
        captured = {}

        def fake_jf_get(url, api_key, params=None, timeout=30):
            captured["get_url"] = url
            return {
                "Id": "item1",
                "Name": "Example",
                "TagItems": [],
                "Tags": ["Drama"],
                "ProviderIds": {},
            }

        def fake_put(url, api_key, json=None, timeout=30):
            captured["put_url"] = url
            captured["payload"] = json
            return {}

        with patch("app.jf_get", side_effect=fake_jf_get):
            with patch("app.jf_put_with_fallback", side_effect=fake_put):
                app_module.jf_update_tags(
                    "http://example.com",
                    "dummy",
                    "item1",
                    ["Comedy"],
                    ["Drama"],
                    user_id="user123",
                )

        expected_fetch = "http://example.com/Users/user123/Items/item1"
        expected_put = "http://example.com/Items/item1"
        self.assertEqual(captured["get_url"], expected_fetch)
        self.assertEqual(captured["put_url"], expected_put)
        self.assertEqual(captured["payload"]["Tags"], ["Comedy"])

    def test_includes_provider_ids_when_present(self):
        captured_payload = {}

        def fake_jf_get(url, api_key, params=None, timeout=30):
            return {
                "Id": "item1",
                "Name": "Example",
                "TagItems": [],
                "Tags": ["Drama"],
                "ProviderIds": {"Imdb": "tt123"},
            }

        def fake_put(url, api_key, json=None, timeout=30):
            captured_payload.update(json or {})
            return {}

        with patch("app.jf_get", side_effect=fake_jf_get):
            with patch("app.jf_put_with_fallback", side_effect=fake_put):
                tags = app_module.jf_update_tags(
                    "http://example.com", "dummy", "item1", ["Comedy"], ["Drama"]
                )

        self.assertEqual(tags, ["Comedy"])
        self.assertEqual(
            captured_payload,
            {
                "Id": "item1",
                "Tags": ["Comedy"],
                "Name": "Example",
                "ProviderIds": {"Imdb": "tt123"},
            },
        )


class ApiApplyUpdateTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_requires_user_id(self):
        response = self.client.post(
            "/api/apply",
            json={"base": "http://example.com", "apiKey": "dummy", "changes": []},
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.is_json)
        self.assertEqual(response.get_json(), {"error": "userId is required"})

    def test_invokes_helper_for_each_change(self):
        calls = []

        def fake_update(base, api_key, item_id, add, remove, user_id=None):
            calls.append((base, api_key, item_id, list(add), list(remove), user_id))
            return ["Merged"]

        payload = {
            "base": "http://example.com",
            "apiKey": "dummy",
            "userId": "user123",
            "changes": [
                {"id": "item1", "add": ["TagA"], "remove": []},
                {"id": "item2", "add": [], "remove": ["Old"]},
            ],
        }

        with patch("app.jf_update_tags", side_effect=fake_update):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            calls,
            [
                ("http://example.com", "dummy", "item1", ["TagA"], [], "user123"),
                ("http://example.com", "dummy", "item2", [], ["Old"], "user123"),
            ],
        )
        data = response.get_json()
        self.assertEqual(len(data.get("updated", [])), 2)
        self.assertEqual(data["updated"][0]["tags"], ["Merged"])

    def test_captures_errors_from_helper(self):
        def fake_update(base, api_key, item_id, add, remove, user_id=None):
            raise RuntimeError("boom")

        payload = {
            "base": "http://example.com",
            "apiKey": "dummy",
            "userId": "user123",
            "changes": [
                {"id": "item1", "add": ["TagA"], "remove": []},
            ],
        }

        with patch("app.jf_update_tags", side_effect=fake_update):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data.get("updated", [])), 1)
        entry = data["updated"][0]
        self.assertEqual(entry.get("added"), [])
        self.assertEqual(entry.get("removed"), [])
        self.assertEqual(entry.get("errors"), ["boom"])


if __name__ == "__main__":
    unittest.main()
