"""
Unit tests for grocy2mealie-sync main module.

Tests cover:
- get_mealie_shopping_list_items: pagination, filtering, duplicate key handling
- add_to_mealie_shopping_list: success, API errors, request exceptions
- get_understock_products: missing products extraction, error handling
"""
import os
import unittest
from unittest.mock import patch, MagicMock
import requests

# Mock environment variables BEFORE importing main
os.environ.update({
    "GROCY_API_URL": "http://test-grocy",
    "GROCY_API_KEY": "test-key",
    "MEALIE_API_URL": "http://test-mealie",
    "MEALIE_API_KEY": "test-mealie-key",
    "MEALIE_SHOPPING_LIST_ID": "test-list-id",
})

import main

class TestGetMealieShoppingListItems(unittest.TestCase):
    """Tests for get_mealie_shopping_list_items function."""

    @patch("main.requests.get")
    def test_single_page_fetch(self, mock_get):
        """Test fetching shopping list with single page."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": "Bread",
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": None,
                }
            ],
            "next": None,
        }
        mock_get.return_value = mock_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertEqual(len(result), 1)
        self.assertIn("bread", result)
        self.assertEqual(result["bread"]["display"], "Bread")
        self.assertEqual(result["bread"]["itemId"], "item1")

    @patch("main.requests.get")
    def test_pagination(self, mock_get):
        """Test fetching shopping list with pagination."""
        page1_response = MagicMock()
        page1_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": "Bread",
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": None,
                }
            ],
            "next": "page2",
        }

        page2_response = MagicMock()
        page2_response.json.return_value = {
            "items": [
                {
                    "id": "item2",
                    "display": "Milk",
                    "shoppingListId": "test-list-id",
                    "foodId": "food2",
                    "food": None,
                }
            ],
            "next": None,
        }

        mock_get.side_effect = [page1_response, page2_response]

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertEqual(len(result), 2)
        self.assertIn("bread", result)
        self.assertIn("milk", result)

    @patch("main.requests.get")
    def test_filter_by_shopping_list_id(self, mock_get):
        """Test that items are filtered by shopping list ID."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": "Bread",
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": None,
                },
                {
                    "id": "item2",
                    "display": "Milk",
                    "shoppingListId": "different-list",
                    "foodId": "food2",
                    "food": None,
                },
            ],
            "next": None,
        }
        mock_get.return_value = mock_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertEqual(len(result), 1)
        self.assertIn("bread", result)
        self.assertNotIn("milk", result)

    @patch("main.requests.get")
    def test_case_insensitive_keys(self, mock_get):
        """Test that keys are lowercased for case-insensitive matching."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": "BREAD",
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": None,
                }
            ],
            "next": None,
        }
        mock_get.return_value = mock_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertIn("bread", result)
        self.assertEqual(result["bread"]["display"], "BREAD")

    @patch("main.requests.get")
    def test_fallback_to_food_name(self, mock_get):
        """Test fallback to food.name when display is missing."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": None,
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": {"id": "food1", "name": "Cheese"},
                }
            ],
            "next": None,
        }
        mock_get.return_value = mock_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertIn("cheese", result)
        self.assertEqual(result["cheese"]["display"], "Cheese")

    @patch("main.requests.get")
    def test_skip_empty_display(self, mock_get):
        """Test that items without display or food name are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": None,
                    "shoppingListId": "test-list-id",
                    "foodId": None,
                    "food": None,
                }
            ],
            "next": None,
        }
        mock_get.return_value = mock_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertEqual(len(result), 0)


class TestAddToMealieShoppingList(unittest.TestCase):
    """Tests for add_to_mealie_shopping_list function."""

    @patch("main.requests.post")
    def test_successful_add_status_200(self, mock_post):
        """Test successful addition with status 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = main.add_to_mealie_shopping_list("Bread", "test-list-id")

        self.assertTrue(result)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["note"], "Bread")
        self.assertEqual(call_kwargs["json"]["quantity"], 1.0)
        self.assertEqual(call_kwargs["json"]["shoppingListId"], "test-list-id")

    @patch("main.requests.post")
    def test_successful_add_status_201(self, mock_post):
        """Test successful addition with status 201."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        result = main.add_to_mealie_shopping_list("Bread", "test-list-id")

        self.assertTrue(result)

    @patch("main.requests.post")
    def test_api_error_status(self, mock_post):
        """Test handling of API error response."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        mock_post.return_value = mock_response

        result = main.add_to_mealie_shopping_list("Bread", "test-list-id")

        self.assertFalse(result)

    @patch("main.requests.post")
    def test_request_exception(self, mock_post):
        """Test handling of request exception."""
        mock_post.side_effect = requests.RequestException("Connection error")

        result = main.add_to_mealie_shopping_list("Bread", "test-list-id")

        self.assertFalse(result)

    @patch("main.requests.post")
    def test_custom_quantity(self, mock_post):
        """Test adding item with custom quantity."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = main.add_to_mealie_shopping_list(
            "Bread", "test-list-id", quantity=2.5
        )

        self.assertTrue(result)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["quantity"], 2.5)

    @patch("main.requests.post")
    def test_strip_whitespace(self, mock_post):
        """Test that item name is stripped of whitespace."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = main.add_to_mealie_shopping_list("  Bread  ", "test-list-id")

        self.assertTrue(result)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["note"], "Bread")


class TestGetUnderstockProducts(unittest.TestCase):
    """Tests for get_understock_products function."""

    @patch("main.grocy.get_volatile_stock")
    def test_extract_missing_products(self, mock_volatile):
        """Test extraction of missing products from volatile stock."""
        mock_item1 = MagicMock()
        mock_item1.name = "Bread"
        mock_item1.id = "prod1"

        mock_item2 = MagicMock()
        mock_item2.name = "Milk"
        mock_item2.id = "prod2"

        mock_volatile_obj = MagicMock()
        mock_volatile_obj.missing_products = [mock_item1, mock_item2]

        mock_volatile.return_value = mock_volatile_obj

        result = main.get_understock_products()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Bread")
        self.assertEqual(result[0]["id"], "prod1")
        self.assertEqual(result[1]["name"], "Milk")
        self.assertEqual(result[1]["id"], "prod2")

    @patch("main.grocy.get_volatile_stock")
    def test_skip_items_without_name(self, mock_volatile):
        """Test that items without name are skipped."""
        mock_item1 = MagicMock()
        mock_item1.name = "Bread"
        mock_item1.id = "prod1"

        mock_item2 = MagicMock()
        mock_item2.name = None
        mock_item2.id = "prod2"

        mock_volatile_obj = MagicMock()
        mock_volatile_obj.missing_products = [mock_item1, mock_item2]

        mock_volatile.return_value = mock_volatile_obj

        result = main.get_understock_products()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Bread")

    @patch("main.grocy.get_volatile_stock")
    def test_request_exception(self, mock_volatile):
        """Test handling of request exception."""
        mock_volatile.side_effect = requests.RequestException("Connection error")

        result = main.get_understock_products()

        self.assertEqual(result, [])

    @patch("main.grocy.get_volatile_stock")
    def test_empty_missing_products(self, mock_volatile):
        """Test handling when no products are missing."""
        mock_volatile_obj = MagicMock()
        mock_volatile_obj.missing_products = []

        mock_volatile.return_value = mock_volatile_obj

        result = main.get_understock_products()

        self.assertEqual(result, [])

    @patch("main.grocy.get_volatile_stock")
    def test_missing_products_attribute(self, mock_volatile):
        """Test handling when missing_products attribute is missing."""
        mock_volatile_obj = MagicMock(spec=[])  # No missing_products attribute
        mock_volatile.return_value = mock_volatile_obj

        result = main.get_understock_products()

        self.assertEqual(result, [])


class TestMainLoop(unittest.TestCase):
    """Tests for main daemon loop function."""

    @patch("main.time.sleep")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_single_iteration(
        self, mock_mealie_items, mock_understock, mock_sleep
    ):
        """Test main loop executes single iteration and sleeps."""
        mock_mealie_items.return_value = {}
        mock_understock.return_value = []
        mock_sleep.side_effect = KeyboardInterrupt()  # Break loop after one iteration

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        mock_mealie_items.assert_called()
        mock_understock.assert_called()
        mock_sleep.assert_called_with(main.INTERVAL)

    @patch("main.time.sleep")
    @patch("main.add_to_mealie_shopping_list")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_adds_missing_item(
        self, mock_mealie_items, mock_understock, mock_add, mock_sleep
    ):
        """Test main loop adds items not in Mealie list."""
        mock_mealie_items.return_value = {"bread": {"display": "Bread"}}
        mock_understock.return_value = [{"name": "Milk", "id": "prod1"}]
        mock_add.return_value = True
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        mock_add.assert_called_once_with(
            "Milk", main.MEALIE_SHOPPING_LIST_ID, quantity=1.0
        )

    @patch("main.time.sleep")
    @patch("main.add_to_mealie_shopping_list")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_skips_existing_items(
        self, mock_mealie_items, mock_understock, mock_add, mock_sleep
    ):
        """Test main loop skips items already in Mealie list."""
        mock_mealie_items.return_value = {"bread": {"display": "Bread"}}
        mock_understock.return_value = [{"name": "Bread", "id": "prod1"}]
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        mock_add.assert_not_called()

    @patch("main.time.sleep")
    @patch("main.add_to_mealie_shopping_list")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_handles_add_failure(
        self, mock_mealie_items, mock_understock, mock_add, mock_sleep
    ):
        """Test main loop handles failed item additions gracefully."""
        mock_mealie_items.return_value = {}
        mock_understock.return_value = [{"name": "Milk", "id": "prod1"}]
        mock_add.return_value = False  # Addition failed
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        mock_add.assert_called_once()

    @patch("main.time.sleep")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_handles_api_exceptions(
        self, mock_mealie_items, mock_understock, mock_sleep
    ):
        """Test main loop catches and logs exceptions without crashing."""
        mock_mealie_items.side_effect = requests.RequestException("API Error")
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        # Should continue looping despite exception
        mock_sleep.assert_called()

    @patch("main.time.sleep")
    @patch("main.add_to_mealie_shopping_list")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_partial_substring_matching(
        self, mock_mealie_items, mock_understock, mock_add, mock_sleep
    ):
        """Test main loop skips items with partial substring match in Mealie."""
        # If Mealie has "Whole Wheat Bread" and Grocy has "Bread",
        # the logic checks if grocy item is substring of existing keys
        mock_mealie_items.return_value = {"whole wheat bread": {"display": "Whole Wheat Bread"}}
        mock_understock.return_value = [
            {"name": "Bread", "id": "prod1"}
        ]
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        # "bread" is in "whole wheat bread", so should be skipped
        mock_add.assert_not_called()

    @patch("main.time.sleep")
    @patch("main.add_to_mealie_shopping_list")
    @patch("main.get_understock_products")
    @patch("main.get_mealie_shopping_list_items")
    def test_main_loop_multiple_items(
        self, mock_mealie_items, mock_understock, mock_add, mock_sleep
    ):
        """Test main loop processes multiple understock items."""
        mock_mealie_items.return_value = {}
        mock_understock.return_value = [
            {"name": "Bread", "id": "prod1"},
            {"name": "Milk", "id": "prod2"},
            {"name": "Cheese", "id": "prod3"},
        ]
        mock_add.return_value = True
        mock_sleep.side_effect = KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            main.main()

        self.assertEqual(mock_add.call_count, 3)


class TestEnvironmentVariables(unittest.TestCase):
    """Tests for environment variable handling."""

    def test_grocy_api_url_stripped(self):
        """Test that GROCY_API_URL has trailing slashes removed."""
        self.assertEqual(main.GROCY_API_URL, "http://test-grocy")
        self.assertFalse(main.GROCY_API_URL.endswith("/"))

    def test_mealie_base_url_stripped(self):
        """Test that MEALIE_BASE_URL has trailing slashes removed."""
        self.assertEqual(main.MEALIE_BASE_URL, "http://test-mealie")
        self.assertFalse(main.MEALIE_BASE_URL.endswith("/"))

    def test_check_interval_parsed_as_int(self):
        """Test that CHECK_INTERVAL is parsed as integer."""
        self.assertIsInstance(main.INTERVAL, int)

    def test_headers_has_auth(self):
        """Test that HEADERS includes Bearer token."""
        self.assertIn("Authorization", main.HEADERS)
        self.assertTrue(main.HEADERS["Authorization"].startswith("Bearer "))

    def test_headers_has_content_type(self):
        """Test that HEADERS includes Content-Type."""
        self.assertIn("Content-Type", main.HEADERS)
        self.assertEqual(main.HEADERS["Content-Type"], "application/json")


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for realistic scenarios."""

    @patch("main.requests.post")
    @patch("main.requests.get")
    def test_sync_cycle_with_real_responses(self, mock_get, mock_post):
        """Test complete sync cycle with realistic API responses."""
        # Mock Mealie GET response
        mealie_response = MagicMock()
        mealie_response.json.return_value = {
            "items": [
                {
                    "id": "item1",
                    "display": "Pasta",
                    "shoppingListId": "test-list-id",
                    "foodId": "food1",
                    "food": None,
                },
                {
                    "id": "item2",
                    "display": "Tomato Sauce",
                    "shoppingListId": "test-list-id",
                    "foodId": "food2",
                    "food": None,
                },
            ],
            "next": None,
        }
        mock_get.return_value = mealie_response

        # Mock Mealie POST response
        post_response = MagicMock()
        post_response.status_code = 201
        mock_post.return_value = post_response

        result = main.get_mealie_shopping_list_items("test-list-id")

        self.assertEqual(len(result), 2)
        self.assertIn("pasta", result)
        self.assertIn("tomato sauce", result)

    @patch("main.grocy.get_volatile_stock")
    def test_grocy_volatile_stock_extraction(self, mock_volatile):
        """Test Grocy volatile stock extraction with realistic data."""
        # Mock product objects
        prod1 = MagicMock()
        prod1.name = "Low Stock Item"
        prod1.id = "123"

        prod2 = MagicMock()
        prod2.name = "Another Item"
        prod2.id = "456"

        volatile_obj = MagicMock()
        volatile_obj.missing_products = [prod1, prod2]

        mock_volatile.return_value = volatile_obj

        result = main.get_understock_products()

        self.assertEqual(len(result), 2)
        names = [item["name"] for item in result]
        self.assertIn("Low Stock Item", names)
        self.assertIn("Another Item", names)

    @patch("main.requests.post")
    def test_mealie_post_with_payload_validation(self, mock_post):
        """Test POST payload structure matches Mealie API requirements."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        main.add_to_mealie_shopping_list("Test Item", "list-123", quantity=2.5)

        # Verify POST was called with correct payload structure
        self.assertTrue(mock_post.called)
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        self.assertIn("quantity", payload)
        self.assertIn("note", payload)
        self.assertIn("shoppingListId", payload)
        self.assertEqual(payload["quantity"], 2.5)
        self.assertEqual(payload["note"], "Test Item")
        self.assertEqual(payload["shoppingListId"], "list-123")

    @patch("main.requests.get")
    def test_mealie_pagination_parameters(self, mock_get):
        """Test pagination parameters sent to Mealie API."""
        response = MagicMock()
        response.json.return_value = {"items": [], "next": None}
        mock_get.return_value = response

        main.get_mealie_shopping_list_items("list-id")

        # Verify correct pagination parameters
        call_kwargs = mock_get.call_args[1]
        self.assertEqual(call_kwargs["params"]["page"], 1)
        self.assertEqual(call_kwargs["params"]["per_page"], 200)


if __name__ == "__main__":
    unittest.main()
