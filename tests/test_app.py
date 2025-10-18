import csv
import io
import os
import sys
import types
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

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

from jellyfin_tag_ui import create_app  # noqa: E402
from jellyfin_tag_ui.config import COLLECTION_ITEM_TYPES  # noqa: E402
from jellyfin_tag_ui.jellyfin_client import jf_post  # noqa: E402
from jellyfin_tag_ui.services import tags as tags_module  # noqa: E402
from jellyfin_tag_ui.services.tags import item_tags, jf_update_tags  # noqa: E402

app = create_app()


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
            "Path": "/media/example.mkv",
        }

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", return_value=item_payload
        ) as mock_get, patch(
            "jellyfin_tag_ui.jellyfin_client.requests.put", return_value=DummyResponse()
        ) as mock_put, patch(
            "jellyfin_tag_ui.jellyfin_client.jf_post"
        ) as mock_post, patch(
            "jellyfin_tag_ui.services.tags.render_nfo", return_value="<item />"
        ) as mock_render, patch(
            "jellyfin_tag_ui.services.tags.Path"
        ) as mock_path:
            mock_post.return_value = {}
            mock_path_instance = mock_path.return_value
            mock_nfo_path = MagicMock()
            mock_parent = MagicMock()
            mock_nfo_path.parent = mock_parent
            mock_path_instance.with_suffix.return_value = mock_nfo_path
            result = jf_update_tags(
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
        mock_render.assert_called_once()
        metadata = mock_render.call_args.args[0]
        self.assertEqual(metadata["Tags"], ["Existing", "New"])
        mock_path.assert_called_once_with(item_payload["Path"])
        mock_path_instance.with_suffix.assert_called_once_with(".nfo")
        mock_parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_nfo_path.write_text.assert_called_once_with("<item />", encoding="utf-8")

    def test_put_falls_back_to_post_when_unsupported(self):
        base = "http://example.com"
        api_key = "token"
        item_id = "12345"
        error_response = DummyResponse(status_code=405)
        unsupported_error = requests.HTTPError("Method Not Allowed")
        unsupported_error.response = error_response
        error_response._http_error = unsupported_error

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get",
            return_value={"Id": item_id, "Tags": [], "TagItems": []},
        ) as mock_get, patch(
            "jellyfin_tag_ui.jellyfin_client.requests.put", return_value=error_response
        ) as mock_put, patch(
            "jellyfin_tag_ui.jellyfin_client.jf_post", return_value={}
        ) as mock_post:
            result = jf_update_tags(
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


class JellyfinClientJsonParsingTest(unittest.TestCase):
    def test_parses_json_with_case_insensitive_content_type(self):
        payload = {"status": "ok"}
        response = DummyResponse(
            json_data=payload,
            headers={"content-type": "Application/Json; charset=utf-8"},
        )

        with patch(
            "jellyfin_tag_ui.jellyfin_client.requests.post", return_value=response
        ):
            result = jf_post("http://example.com/Items", "token")

        self.assertEqual(result, payload)


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

    def test_includes_inherited_tags(self):
        item = {"TagItems": [], "Tags": [], "InheritedTags": ["Parent"]}

        self.assertEqual(item_tags(item), ["Parent"])

    def test_trims_whitespace_and_ignores_empty_tags(self):
        item = {
            "TagItems": [{"Name": " Action "}, {"Name": "Drama  "}],
            "Tags": ["Action  ", "  Mystery  ", ""],
            "InheritedTags": [" Action ", "   "],
        }

        self.assertEqual(item_tags(item), ["Action", "Drama", "Mystery"])


class ApiTagsPaginationTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_user_endpoint_accumulates_multiple_pages(self):
        payloads = [
            {
                "Items": [
                    {"Name": "Action", "ItemCount": 2},
                    {"Name": "Drama", "ItemCount": 1},
                ],
                "TotalRecordCount": 3,
            },
            {
                "Items": [
                    {"Name": "Comedy", "ItemCount": 4},
                ],
                "TotalRecordCount": 3,
            },
        ]
        calls: List[Dict[str, Any]] = []

        def fake_jf_get(url, api_key, params=None, timeout=30):
            call_index = len(calls)
            calls.append({"url": url, "params": dict(params or {})})
            self.assertTrue(url.endswith("/Users/user/Items/Tags"))
            self.assertEqual(params.get("Limit"), tags_module.TAG_PAGE_LIMIT)
            expected_start = 0 if call_index == 0 else 2
            self.assertEqual(params.get("StartIndex"), expected_start)
            try:
                return payloads[call_index]
            except IndexError as exc:  # pragma: no cover - defensive
                raise AssertionError("Unexpected pagination request") from exc

        with patch("jellyfin_tag_ui.services.tags.TAG_PAGE_LIMIT", 2), patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=fake_jf_get
        ):
            response = self.client.post(
                "/api/tags",
                json={
                    "base": "http://example.com",
                    "apiKey": "token",
                    "libraryId": "lib",
                    "userId": "user",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["source"], "users-items-tags")
        self.assertEqual(data["tags"], ["Comedy", "Action", "Drama"])
        self.assertEqual(len(calls), 2)

    def test_global_endpoint_accumulates_multiple_pages(self):
        payloads = [
            {
                "Items": [
                    {"Name": "Alpha", "ItemCount": 5},
                    {"Name": "Beta", "ItemCount": 3},
                ],
                "TotalRecordCount": 3,
            },
            {
                "Items": [
                    {"Name": "Gamma", "ItemCount": 1},
                ],
                "TotalRecordCount": 3,
            },
        ]
        calls: List[Dict[str, Any]] = []

        def fake_jf_get(url, api_key, params=None, timeout=30):
            call_index = len(calls)
            calls.append({"url": url, "params": dict(params or {})})
            self.assertTrue(url.endswith("/Items/Tags"))
            self.assertEqual(params.get("Limit"), tags_module.TAG_PAGE_LIMIT)
            expected_start = 0 if call_index == 0 else 2
            self.assertEqual(params.get("StartIndex"), expected_start)
            try:
                return payloads[call_index]
            except IndexError as exc:  # pragma: no cover - defensive
                raise AssertionError("Unexpected pagination request") from exc

        with patch("jellyfin_tag_ui.services.tags.TAG_PAGE_LIMIT", 2), patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=fake_jf_get
        ):
            response = self.client.post(
                "/api/tags",
                json={
                    "base": "http://example.com",
                    "apiKey": "token",
                    "libraryId": "lib",
                },
            )

        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["source"], "items-tags")
        self.assertEqual(data["tags"], ["Alpha", "Beta", "Gamma"])
        self.assertEqual(len(calls), 2)


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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured["fields"] = fields
            return {"Items": [], "TotalRecordCount": 0}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
        self.assertIn("InheritedTags", captured["fields"])

    def test_api_items_filters_by_inherited_tags(self):
        responses = [
            {
                "Items": [
                    {
                        "Id": "inherited",
                        "Type": "Movie",
                        "Name": "Inherited",
                        "Path": "/inherited.mkv",
                        "Tags": [],
                        "TagItems": [],
                        "InheritedTags": ["Legacy"],
                    }
                ],
                "TotalRecordCount": 1,
            },
            {"Items": [], "TotalRecordCount": 1},
        ]

        call_count = {"index": 0}

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            idx = call_count["index"]
            call_count["index"] += 1
            if idx < len(responses):
                return responses[idx]
            return {"Items": [], "TotalRecordCount": 1}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Legacy",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["TotalMatchCount"], 1)
        self.assertEqual(data["ReturnedCount"], 1)
        self.assertEqual(len(data["Items"]), 1)
        self.assertEqual(data["Items"][0]["Id"], "inherited")
        self.assertEqual(data["Items"][0]["Tags"], ["Legacy"])

    def test_api_items_filters_using_trimmed_tags(self):
        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            return {
                "Items": [
                    {
                        "Id": "trimmed",
                        "Type": "Movie",
                        "Name": "Trimmed",
                        "Path": "/trimmed.mkv",
                        "Tags": ["Action  ", "  Mystery  "],
                        "TagItems": [
                            {"Name": " Action "},
                            {"Name": "Drama  "},
                        ],
                        "InheritedTags": [" Action "],
                    }
                ],
                "TotalRecordCount": 1,
            }

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Action",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["ReturnedCount"], 1)
        self.assertEqual(len(data["Items"]), 1)
        self.assertEqual(data["Items"][0]["Id"], "trimmed")
        self.assertEqual(
            data["Items"][0]["Tags"],
            ["Action", "Drama", "Mystery"],
        )

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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured["limit"] = limit
            return {"Items": [], "TotalRecordCount": 0}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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

    def test_api_items_passes_sort_parameters(self):
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured["sort_by"] = sort_by
            captured["sort_order"] = sort_order
            return {"Items": [], "TotalRecordCount": 0}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "sortBy": "PremiereDate",
                    "sortOrder": "Descending",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["sort_by"], "PremiereDate")
        self.assertEqual(captured["sort_order"], "Descending")

    def test_api_items_forwards_title_query_to_page_items(self):
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured["search_term"] = search_term
            return {"Items": [], "TotalRecordCount": 0}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "titleQuery": "  Example  ",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["search_term"], "Example")

    def test_api_items_filters_by_title_query_locally(self):
        responses = [
            {
                "Items": [
                    {
                        "Id": "alpha",
                        "Type": "Movie",
                        "Name": "Alpha",
                        "SortName": "Alpha",
                        "Path": "/alpha.mkv",
                        "Tags": [],
                        "TagItems": [],
                    },
                    {
                        "Id": "gamma",
                        "Type": "Movie",
                        "Name": "Unrelated",
                        "SortName": "Gamma Chronicles",
                        "Path": "/gamma.mkv",
                        "Tags": [],
                        "TagItems": [],
                    },
                ],
                "TotalRecordCount": 2,
            },
            {"Items": [], "TotalRecordCount": 2},
        ]
        call_index = {"value": 0}

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            idx = call_index["value"]
            call_index["value"] += 1
            return responses[idx]

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "titleQuery": "  gaM  ",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["TotalMatchCount"], 1)
        self.assertEqual(data["ReturnedCount"], 1)
        self.assertEqual(len(data["Items"]), 1)
        self.assertEqual(data["Items"][0]["Id"], "gamma")

    def test_api_items_includes_all_types_when_filter_blank(self):
        captured_params = []

        def fake_jf_get(url, api_key, params=None, timeout=30):
            captured_params.append(dict(params or {}))
            if len(captured_params) == 1:
                return {
                    "Items": [
                        {
                            "Id": "movie-1",
                            "Type": "Movie",
                            "Name": "Movie 1",
                            "Path": "/movie-1.mkv",
                            "Tags": ["Alpha"],
                        },
                        {
                            "Id": "series-1",
                            "Type": "Series",
                            "Name": "Series 1",
                            "Path": "/series-1.mkv",
                            "Tags": ["Beta"],
                        },
                    ],
                    "TotalRecordCount": 2,
                }
            return {"Items": [], "TotalRecordCount": 2}

        with patch("jellyfin_tag_ui.services.items.jf_get", side_effect=fake_jf_get):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": [],
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["ReturnedCount"], 2)
        self.assertEqual(
            [item["Id"] for item in data["Items"]], ["movie-1", "series-1"]
        )
        self.assertTrue(captured_params)
        for params in captured_params:
            self.assertNotIn("IncludeItemTypes", params)

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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
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

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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

    def test_api_items_handles_inaccurate_total_record_count(self):
        starts = []

        first_page = [
            {
                "Id": "match-1",
                "Type": "Movie",
                "Name": "Match 1",
                "Path": "/match-1.mkv",
                "Tags": ["Keep"],
                "TagItems": [],
            },
            {
                "Id": "other-1",
                "Type": "Movie",
                "Name": "Other 1",
                "Path": "/other-1.mkv",
                "Tags": ["Other"],
                "TagItems": [],
            },
        ]

        second_page = [
            {
                "Id": "match-2",
                "Type": "Movie",
                "Name": "Match 2",
                "Path": "/match-2.mkv",
                "Tags": ["Keep"],
                "TagItems": [],
            },
            {
                "Id": "match-3",
                "Type": "Movie",
                "Name": "Match 3",
                "Path": "/match-3.mkv",
                "Tags": ["Keep"],
                "TagItems": [],
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 2}
            if start == 2:
                return {"Items": second_page, "TotalRecordCount": 2}
            return {"Items": [], "TotalRecordCount": 2}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Keep",
                    "limit": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn((0, 2), starts)
        self.assertIn((2, 2), starts)
        self.assertEqual(data["TotalMatchCount"], 3)

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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            slice_end = start + limit
            return {
                "Items": records[start:slice_end],
                "TotalRecordCount": len(records),
            }

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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

    def test_api_items_second_page_empty_after_filtering(self):
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
                "Id": "other-2",
                "Type": "Movie",
                "Name": "Other 2",
                "Path": "/other-2.mkv",
                "Tags": ["Other"],
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            if start >= len(records):
                return {"Items": [], "TotalRecordCount": len(records)}
            slice_end = min(start + limit, len(records))
            return {
                "Items": records[start:slice_end],
                "TotalRecordCount": len(records),
            }

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
                    "limit": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreaterEqual(len(starts), 3)
        self.assertIn((0, 1), starts)
        self.assertIn((1, 1), starts)
        self.assertIn((2, 1), starts)
        self.assertEqual(data["TotalMatchCount"], 1)
        self.assertEqual(data["TotalRecordCount"], 1)
        self.assertEqual(data["ReturnedCount"], 0)
        self.assertEqual(data["Items"], [])

    def test_api_items_handles_server_page_cap(self):
        starts = []

        def make_item(idx: int) -> Dict[str, Any]:
            return {
                "Id": f"match-{idx}",
                "Type": "Movie",
                "Name": f"Match {idx}",
                "Path": f"/match-{idx}.mkv",
                "Tags": ["Keep"],
                "TagItems": [],
            }

        first_page = [make_item(idx) for idx in range(50)]
        second_page = [make_item(idx) for idx in range(50, 100)]
        third_page = [make_item(idx) for idx in range(100, 120)]

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 120}
            if start == len(first_page):
                return {"Items": second_page, "TotalRecordCount": 120}
            if start == len(first_page) + len(second_page):
                return {"Items": third_page, "TotalRecordCount": 120}
            return {"Items": [], "TotalRecordCount": 120}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "includeTags": "Keep",
                    "limit": 100,
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn((0, 100), starts)
        self.assertIn((50, 50), starts)
        self.assertIn((100, 50), starts)
        self.assertEqual(data["TotalMatchCount"], 120)
        self.assertEqual(data["ReturnedCount"], 100)
        self.assertEqual(len(data["Items"]), 100)
        self.assertEqual(data["Items"][0]["Id"], "match-0")

    def test_api_items_sorts_results_locally_by_name(self):
        captured_sort = []

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured_sort.append((sort_by, sort_order))
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "b",
                            "Type": "Movie",
                            "Name": "Bravo",
                            "Path": "/b.mkv",
                            "Tags": ["Tag"],
                        },
                        {
                            "Id": "a",
                            "Type": "Movie",
                            "Name": "Alpha",
                            "Path": "/a.mkv",
                            "Tags": ["Tag"],
                        },
                    ],
                    "TotalRecordCount": 2,
                }
            return {"Items": [], "TotalRecordCount": 2}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "sortBy": "SortName",
                    "sortOrder": "Ascending",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([item["Name"] for item in data["Items"]], ["Alpha", "Bravo"])
        self.assertIn(("SortName", "Ascending"), captured_sort)

    def test_api_items_sorts_results_locally_by_date(self):
        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "legacy",
                            "Type": "Movie",
                            "Name": "Legacy",
                            "PremiereDate": "2010-01-01T00:00:00Z",
                            "Path": "/legacy.mkv",
                            "Tags": [],
                        },
                        {
                            "Id": "modern",
                            "Type": "Movie",
                            "Name": "Modern",
                            "PremiereDate": "2020-01-01T00:00:00Z",
                            "Path": "/modern.mkv",
                            "Tags": [],
                        },
                        {
                            "Id": "year-only",
                            "Type": "Movie",
                            "Name": "Year Only",
                            "ProductionYear": 2022,
                            "Path": "/year-only.mkv",
                            "Tags": [],
                        },
                    ],
                    "TotalRecordCount": 3,
                }
            return {"Items": [], "TotalRecordCount": 3}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/items",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "sortBy": "PremiereDate",
                    "sortOrder": "Descending",
                },
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(
            [item["Id"] for item in data["Items"]],
            ["year-only", "modern", "legacy"],
        )


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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
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

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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

    def test_api_export_respects_sorting(self):
        captured_orders = []

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            captured_orders.append((sort_by, sort_order))
            if start == 0:
                return {
                    "Items": [
                        {
                            "Id": "b",
                            "Name": "Bravo",
                            "Path": "/b.mkv",
                            "ProviderIds": {},
                            "Type": "Movie",
                            "TagItems": [],
                            "Tags": [],
                        },
                        {
                            "Id": "a",
                            "Name": "Alpha",
                            "Path": "/a.mkv",
                            "ProviderIds": {},
                            "Type": "Movie",
                            "TagItems": [],
                            "Tags": [],
                        },
                    ],
                    "TotalRecordCount": 2,
                }
            return {"Items": [], "TotalRecordCount": 2}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
            response = self.client.post(
                "/api/export",
                json={
                    "base": "http://example.com",
                    "apiKey": "dummy",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie"],
                    "sortBy": "SortName",
                    "sortOrder": "Ascending",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(("SortName", "Ascending"), captured_orders)
        reader = csv.DictReader(io.StringIO(response.data.decode("utf-8")))
        names = [row["name"] for row in reader]
        self.assertEqual(names, ["Alpha", "Bravo"])

    def test_api_export_handles_inaccurate_total_record_count(self):
        page_calls = []

        first_page = [
            {
                "Id": f"bulk-{idx}",
                "Type": "Movie",
                "Name": f"Bulk {idx}",
                "Path": f"/bulk-{idx}.mkv",
                "Tags": ["Bulk"],
                "TagItems": [],
            }
            for idx in range(500)
        ]

        second_page = [
            {
                "Id": f"tail-{idx}",
                "Type": "Movie",
                "Name": f"Tail {idx}",
                "Path": f"/tail-{idx}.mkv",
                "Tags": ["Tail"],
                "TagItems": [],
            }
            for idx in range(3)
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            page_calls.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 200}
            if start == len(first_page):
                return {"Items": second_page, "TotalRecordCount": 200}
            return {"Items": [], "TotalRecordCount": 200}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
        csv_output = response.data.decode("utf-8")
        self.assertIn((0, 500), page_calls)
        self.assertIn((len(first_page), 500), page_calls)
        self.assertIn("tail-1", csv_output)

    def test_api_export_handles_server_page_cap(self):
        page_calls = []

        def make_item(prefix: str, idx: int) -> Dict[str, Any]:
            return {
                "Id": f"{prefix}-{idx}",
                "Type": "Movie",
                "Name": f"{prefix.title()} {idx}",
                "Path": f"/{prefix}-{idx}.mkv",
                "Tags": [prefix.title()],
                "TagItems": [{"Name": prefix.title()}],
            }

        first_page = [make_item("alpha", idx) for idx in range(200)]
        second_page = [make_item("beta", idx) for idx in range(200, 400)]
        third_page = [make_item("gamma", idx) for idx in range(400, 600)]

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            page_calls.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 600}
            if start == len(first_page):
                return {"Items": second_page, "TotalRecordCount": 600}
            if start == len(first_page) + len(second_page):
                return {"Items": third_page, "TotalRecordCount": 600}
            return {"Items": [], "TotalRecordCount": 600}

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
        csv_output = response.data.decode("utf-8")
        self.assertIn((0, 500), page_calls)
        self.assertIn((200, 200), page_calls)
        self.assertIn((400, 200), page_calls)
        self.assertIn((600, 200), page_calls)
        self.assertIn("gamma-450", csv_output)


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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
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

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
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

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ):
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
            search_term=None,
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

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=RuntimeError("boom")
        ):
            with patch(
                "jellyfin_tag_ui.services.items.page_items", side_effect=fake_page_items
            ):
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

    def test_aggregated_fallback_fetches_until_short_page(self):
        starts = []

        def make_item(tag: str) -> Dict[str, Any]:
            return {"TagItems": [{"Name": tag}], "Tags": [], "InheritedTags": []}

        first_page = [make_item("Alpha") for _ in range(500)]
        second_page = [make_item("Beta") for _ in range(50)]

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 425}
            if start == 500:
                return {"Items": second_page, "TotalRecordCount": 425}
            return {"Items": [], "TotalRecordCount": 425}

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=RuntimeError("boom")
        ):
            with patch(
                "jellyfin_tag_ui.services.items.page_items", side_effect=fake_page_items
            ):
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
        self.assertIn((0, 500), starts)
        self.assertIn((500, 500), starts)
        self.assertEqual(data.get("tags"), ["Alpha", "Beta"])

    def test_aggregated_fallback_handles_server_page_cap(self):
        starts = []

        def make_item(tag: str, idx: int) -> Dict[str, Any]:
            return {
                "Id": f"{tag.lower()}-{idx}",
                "TagItems": [{"Name": tag}],
                "Tags": [],
                "InheritedTags": [],
            }

        first_page = [make_item("Alpha", idx) for idx in range(200)]
        second_page = [make_item("Beta", idx) for idx in range(200, 400)]
        third_page = [make_item("Gamma", idx) for idx in range(400, 600)]

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            starts.append((start, limit))
            if start == 0:
                return {"Items": first_page, "TotalRecordCount": 600}
            if start == len(first_page):
                return {"Items": second_page, "TotalRecordCount": 600}
            if start == len(first_page) + len(second_page):
                return {"Items": third_page, "TotalRecordCount": 600}
            return {"Items": [], "TotalRecordCount": 600}

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=RuntimeError("boom")
        ):
            with patch(
                "jellyfin_tag_ui.services.items.page_items", side_effect=fake_page_items
            ):
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
        self.assertIn((0, 500), starts)
        self.assertIn((200, 200), starts)
        self.assertIn((400, 200), starts)
        self.assertIn((600, 200), starts)
        self.assertEqual(data.get("tags"), ["Alpha", "Beta", "Gamma"])


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
            with patch("jellyfin_tag_ui.routes.users.jf_get", side_effect=fake_jf_get):
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

        with patch("jellyfin_tag_ui.services.tags.jf_get", side_effect=fake_jf_get):
            with patch(
                "jellyfin_tag_ui.services.tags.jf_put_with_fallback",
                side_effect=fake_put,
            ):
                final_tags = jf_update_tags(
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

        with patch("jellyfin_tag_ui.services.tags.jf_get", side_effect=fake_jf_get):
            with patch(
                "jellyfin_tag_ui.services.tags.jf_put_with_fallback",
                side_effect=fake_put,
            ):
                jf_update_tags(
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

        with patch("jellyfin_tag_ui.services.tags.jf_get", side_effect=fake_jf_get):
            with patch(
                "jellyfin_tag_ui.services.tags.jf_put_with_fallback",
                side_effect=fake_put,
            ):
                tags = jf_update_tags(
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

        with patch(
            "jellyfin_tag_ui.routes.apply.jf_update_tags", side_effect=fake_update
        ):
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

        with patch(
            "jellyfin_tag_ui.routes.apply.jf_update_tags", side_effect=fake_update
        ):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data.get("updated", [])), 1)
        entry = data["updated"][0]
        self.assertEqual(entry.get("added"), [])
        self.assertEqual(entry.get("removed"), [])
        self.assertEqual(entry.get("errors"), ["boom"])

    def test_reports_jellyfin_http_error_message(self):
        error_payload = {
            "Message": "Tag update failed",
            "ErrorCode": "InvalidTag",
            "ResponseStatus": {"Message": "The tag value is invalid."},
        }
        error_response = DummyResponse(status_code=400, json_data=error_payload)
        error_response.reason = "Bad Request"
        error_response.url = "http://example.com/Items/item1"
        http_error = requests.HTTPError(
            "400 Client Error: Bad Request for url: http://example.com/Items/item1"
        )
        http_error.response = error_response

        payload = {
            "base": "http://example.com",
            "apiKey": "dummy",
            "userId": "user123",
            "changes": [
                {"id": "item1", "add": ["TagA"], "remove": []},
            ],
        }

        with patch(
            "jellyfin_tag_ui.routes.apply.jf_update_tags", side_effect=http_error
        ):
            response = self.client.post("/api/apply", json=payload)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data.get("updated", [])), 1)
        entry = data["updated"][0]
        self.assertEqual(entry.get("added"), [])
        self.assertEqual(entry.get("removed"), [])
        errors = entry.get("errors") or []
        self.assertEqual(len(errors), 1)
        self.assertIn("Tag update failed", errors[0])
        self.assertIn("InvalidTag", errors[0])


class ApiTagsOrderingTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_user_endpoint_orders_by_count_then_name(self):
        payload = {
            "Items": [
                {"Name": "Comedy", "ItemCount": 5},
                {"Name": "action", "ItemCount": 5},
                {"Name": "Drama", "ItemCount": 2},
            ]
        }

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", return_value=payload
        ) as mock_get:
            response = self.client.post(
                "/api/tags",
                json={
                    "base": "http://example.com",
                    "apiKey": "token",
                    "libraryId": "lib",
                    "userId": "user",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"tags": ["action", "Comedy", "Drama"], "source": "users-items-tags"},
        )
        mock_get.assert_called_once()

    def test_aggregated_fallback_orders_by_frequency(self):
        failures = [requests.HTTPError("boom"), requests.HTTPError("boom")]

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
        ):
            if start == 0:
                return {
                    "Items": [
                        {"TagItems": [{"Name": "Sci-Fi"}], "Tags": ["Drama"]},
                        {"TagItems": [], "Tags": ["drama", "Comedy"]},
                    ],
                    "TotalRecordCount": 3,
                }
            if start == 2:
                return {
                    "Items": [{"TagItems": [{"Name": "Sci-Fi"}], "Tags": []}],
                    "TotalRecordCount": 3,
                }
            return {"Items": [], "TotalRecordCount": 3}

        with patch(
            "jellyfin_tag_ui.services.tags.jf_get", side_effect=failures
        ) as mock_get, patch(
            "jellyfin_tag_ui.services.items.page_items", side_effect=fake_page_items
        ) as mock_page_items:
            response = self.client.post(
                "/api/tags",
                json={
                    "base": "http://example.com",
                    "apiKey": "token",
                    "libraryId": "lib",
                    "userId": "user",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"tags": ["Drama", "Sci-Fi", "Comedy"], "source": "aggregated"},
        )
        self.assertEqual(mock_get.call_count, 2)
        self.assertGreaterEqual(mock_page_items.call_count, 2)


class ApiExportTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_export_normalizes_filters_and_streams_filtered_rows(self):
        captured_calls: List[Dict[str, Any]] = []

        first_payload = {
            "Items": [
                {
                    "Id": "match",
                    "Type": "Movie",
                    "Name": "Example Match",
                    "SortName": "Example Match",
                    "Path": "/media/match.mkv",
                    "TagItems": [{"Name": "Action"}],
                    "Tags": ["Drama"],
                    "InheritedTags": [],
                },
                {
                    "Id": "skip-tag",
                    "Type": "Movie",
                    "Name": "Example Skip",
                    "SortName": "Example Skip",
                    "Path": "/media/skip.mkv",
                    "TagItems": [],
                    "Tags": ["Skip"],
                    "InheritedTags": [],
                },
                {
                    "Id": "collection",
                    "Type": "BoxSet",
                    "Name": "Example Collection",
                    "SortName": "Example Collection",
                    "Path": "/media/collection",
                    "TagItems": [],
                    "Tags": ["Action"],
                    "InheritedTags": [],
                },
                {
                    "Id": "wrong-title",
                    "Type": "Episode",
                    "Name": "Irrelevant",
                    "SortName": "Irrelevant",
                    "Path": "/media/wrong.mkv",
                    "TagItems": [],
                    "Tags": ["Action", "Drama"],
                    "InheritedTags": [],
                },
            ],
            "TotalRecordCount": 4,
        }

        def fake_page_items(
            base,
            api_key,
            user_id,
            lib_id,
            include_types,
            fields,
            start,
            limit,
            search_term=None,
            exclude_types=None,
            sort_by=None,
            sort_order=None,
        ):
            call_details = {
                "base": base,
                "api_key": api_key,
                "user_id": user_id,
                "lib_id": lib_id,
                "include_types": list(include_types or []),
                "fields": list(fields or []),
                "start": start,
                "limit": limit,
                "search_term": search_term,
                "exclude_types": tuple(exclude_types or ()),
                "sort_by": sort_by,
                "sort_order": sort_order,
            }
            captured_calls.append(call_details)
            if start == 0:
                return first_payload
            return {"Items": [], "TotalRecordCount": 4}

        captured_csv: Dict[str, Any] = {}

        def fake_send_file(mem, mimetype, as_attachment, download_name):
            payload = mem.getvalue()
            captured_csv.update(
                {
                    "content": payload,
                    "mimetype": mimetype,
                    "as_attachment": as_attachment,
                    "download_name": download_name,
                }
            )
            response = app.response_class(payload, mimetype=mimetype)
            response.direct_passthrough = False
            return response

        with patch(
            "jellyfin_tag_ui.routes.items.page_items", side_effect=fake_page_items
        ) as mock_page_items, patch(
            "jellyfin_tag_ui.routes.items.send_file", side_effect=fake_send_file
        ) as mock_send_file:
            response = self.client.post(
                "/api/export",
                json={
                    "base": "http://example.com",
                    "apiKey": "token",
                    "userId": "user",
                    "libraryId": "lib",
                    "types": ["Movie ", "Episode", "", None],
                    "includeTags": " Action ;Drama ,Action ",
                    "excludeTags": " Skip ;Other ",
                    "titleQuery": "  Example  ",
                    "excludeCollections": True,
                    "sortBy": "PremiereDate",
                    "sortOrder": "desc",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(captured_calls), 1)
        call = captured_calls[0]
        self.assertEqual(call["base"], "http://example.com")
        self.assertEqual(call["api_key"], "token")
        self.assertEqual(call["user_id"], "user")
        self.assertEqual(call["lib_id"], "lib")
        self.assertEqual(call["include_types"], ["Movie", "Episode"])
        self.assertEqual(
            call["fields"],
            [
                "TagItems",
                "InheritedTags",
                "Name",
                "Path",
                "ProviderIds",
                "Type",
                "Tags",
                "SortName",
                "PremiereDate",
                "ProductionYear",
            ],
        )
        self.assertEqual(call["start"], 0)
        self.assertEqual(call["limit"], 500)
        self.assertEqual(call["search_term"], "Example")
        self.assertEqual(call["exclude_types"], COLLECTION_ITEM_TYPES)
        self.assertEqual(call["sort_by"], "PremiereDate")
        self.assertEqual(call["sort_order"], "Descending")

        mock_page_items.assert_called()
        mock_send_file.assert_called_once()
        self.assertEqual(captured_csv["mimetype"], "text/csv")
        self.assertTrue(captured_csv["as_attachment"])
        self.assertEqual(captured_csv["download_name"], "tags_export.csv")

        csv_bytes = captured_csv["content"]
        self.assertIsInstance(csv_bytes, (bytes, bytearray))
        csv_text = csv_bytes.decode("utf-8")
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        self.assertEqual(
            rows,
            [
                {
                    "id": "match",
                    "type": "Movie",
                    "name": "Example Match",
                    "path": "/media/match.mkv",
                    "tags": "Action;Drama",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
