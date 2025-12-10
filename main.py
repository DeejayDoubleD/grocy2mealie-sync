"""
Grocy to Mealie Sync Service.

Synchronizes missing products from Grocy (inventory system) to Mealie
(meal planning system) shopping list. Runs as a daemon with configurable
sync intervals.
"""
from typing import Dict, List
import os
import sys
import time
import logging
import requests
from pygrocy2.grocy_api_client import GrocyApiClient

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("grocy-mealie-sync")

# ------------------------------------------------------------
# Environment variables (Docker-ready)
# ------------------------------------------------------------
GROCY_API_URL = os.getenv("GROCY_API_URL", "").rstrip("/")
GROCY_API_KEY = os.getenv("GROCY_API_KEY", "")

MEALIE_BASE_URL = os.getenv("MEALIE_API_URL", "").rstrip("/")  # e.g. http://mealie:9000
MEALIE_API_KEY = os.getenv("MEALIE_API_KEY", "")
MEALIE_SHOPPING_LIST_ID = os.getenv("MEALIE_SHOPPING_LIST_ID", "")

INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))  # default = 10 min

if not all([GROCY_API_URL, GROCY_API_KEY, MEALIE_BASE_URL, MEALIE_API_KEY,
            MEALIE_SHOPPING_LIST_ID]):
    raise SystemExit(
        "❌ Environment variables missing. Please set GROCY_API_URL, GROCY_API_KEY, "
        "MEALIE_API_URL, MEALIE_API_KEY, MEALIE_SHOPPING_LIST_ID"
    )

# ------------------------------------------------------------
# Initialize Grocy (pygrocy)
# - Use pygrocy's built-in helpers such as missing_products()
#   (robust / matches the library docs)
# ------------------------------------------------------------
grocy = GrocyApiClient(GROCY_API_URL, GROCY_API_KEY, 9283)

# ------------------------------------------------------------
# Mealie Helper Functions (uses /api/households/shopping/items)
# ------------------------------------------------------------
HEADERS = {
    "Authorization": f"Bearer {MEALIE_API_KEY}",
    "Content-Type": "application/json",
}

def get_mealie_shopping_list_items(shopping_list_id: str) -> Dict[str, dict]:
    """
    Fetches all entries from /api/households/shopping/items (paginated)
    and filters by shoppingListId.

    Args:
        shopping_list_id: The shopping list ID to filter by.

    Returns:
        Dict mapping display_lower to {display, foodId, itemId}.
    """
    url = f"{MEALIE_BASE_URL}/api/households/shopping/items"
    items_dict = {}
    page = 1
    per_page = 200

    while True:
        params = {"page": page, "per_page": per_page}
        resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        for it in items:
            if it.get("shoppingListId") != shopping_list_id:
                continue
            display = (it.get("display") or (it.get("food") or {}).get("name") or "").strip()
            if not display:
                continue
            items_dict[display.lower()] = {
                "display": display,
                "foodId": it.get("foodId") or (it.get("food") or {}).get("id"),
                "itemId": it.get("id")
            }

        if not data.get("next"):
            break
        page += 1

    logger.info("Mealie: %d existing shopping list items found.", len(items_dict))
    return items_dict

def add_to_mealie_shopping_list(item_name: str, shopping_list_id: str,
                                quantity: float = 1.0) -> bool:
    """
    Add an item to the Mealie shopping list.

    Args:
        item_name: The name of the item to add.
        shopping_list_id: The shopping list ID.
        quantity: The quantity of the item (default 1.0).

    Returns:
        True if successful, False otherwise.
    """
    url = f"{MEALIE_BASE_URL}/api/households/shopping/items"
    name = item_name.strip()

    payload = {
        "quantity": float(quantity),
        "note": name,
        "shoppingListId": shopping_list_id,
    }

    try:
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=10)
        if resp.status_code in (200, 201):
            logger.info("Mealie: added → %s", name)
            return True

        logger.error("Error during POST (%s): %s", resp.status_code, resp.text)
        return False

    except requests.RequestException as e:
        logger.error("POST error: %s", e)
        return False

# ------------------------------------------------------------
# Grocy Helper (corrected)
# - Uses pygrocy2 missing_products() / volatile stock helpers
#   instead of own, error-prone product+stock logic
# ------------------------------------------------------------
def get_understock_products() -> List[Dict[str, str]]:
    """
    Get products that are below minimum stock according to Grocy.

    Uses get_volatile_stock() from pygrocy2 and extracts the
    'missing_products' list.

    Returns:
        List of dicts with 'id' and 'name' keys.
    """
    try:
        volatile = grocy.get_volatile_stock()
    except requests.RequestException as e:
        logger.error("Error while requesting Grocy volatile stock: %s", e)
        return []

    products = []

    missing_products = getattr(volatile, "missing_products", []) or []
    for item in missing_products:
        name = getattr(item, "name", None)
        pid = getattr(item, "id", None)

        if name:
            products.append({
                "id": pid,
                "name": name
            })

    logger.info(
        "Grocy: %d products below minimum stock (volatile.missing_products).",
        len(products)
    )

    return products

# ------------------------------------------------------------
# Health Check
# - Verifies API connectivity and service status
# ------------------------------------------------------------
def health_check() -> Dict[str, dict]:
    """
    Check health status of the sync service.

    Verifies:
    - Grocy API is reachable
    - Mealie API is reachable
    - Authentication tokens are valid

    Returns:
        Dict with status and details: {
            "status": "healthy" | "unhealthy",
            "grocy": {"reachable": bool, "error": str or None},
            "mealie": {"reachable": bool, "error": str or None}
        }
    """
    health = {
        "status": "healthy",
        "grocy": {"reachable": False, "error": None},
        "mealie": {"reachable": False, "error": None},
    }

    # Check Grocy connectivity
    try:
        grocy.get_volatile_stock()
        health["grocy"]["reachable"] = True
        logger.info("✔ Grocy API is reachable")
    except requests.RequestException as e:
        health["grocy"]["reachable"] = False
        health["grocy"]["error"] = str(e)
        health["status"] = "unhealthy"
        logger.error("❌ Grocy API unreachable: %s", e)

    # Check Mealie connectivity
    try:
        url = f"{MEALIE_BASE_URL}/api/households/shopping/items"
        resp = requests.get(
            url, headers=HEADERS, params={"page": 1, "per_page": 1}, timeout=10
        )
        resp.raise_for_status()
        health["mealie"]["reachable"] = True
        logger.info("✔ Mealie API is reachable")
    except requests.RequestException as e:
        health["mealie"]["reachable"] = False
        health["mealie"]["error"] = str(e)
        health["status"] = "unhealthy"
        logger.error("❌ Mealie API unreachable: %s", e)

    return health

# ------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------
def main():
    """
    Main daemon loop that continuously syncs Grocy understock to Mealie.

    Fetches Mealie shopping list items, retrieves understock products from Grocy,
    and adds missing items to Mealie. Runs in infinite loop with configurable
    interval between syncs.
    """
    logger.info("🔄 Grocy → Mealie sync started (using pygrocy missing_products)…")

    while True:
        try:
            # Mealie: load existing shopping list entries (prevents duplicates)
            mealie_items = get_mealie_shopping_list_items(MEALIE_SHOPPING_LIST_ID)

            # Grocy: below-minimum-stock products via pygrocy helper
            understock = get_understock_products()
            existing_keys = {k.strip().lower() for k in mealie_items}
            for item in understock:
                name_key = item.get("name", "").strip().lower()
                if any(name_key in key for key in existing_keys):
                    logger.info("✔ '%s' already in the Mealie list.", item['name'])
                    continue

                logger.info("➕ '%s' will be added to Mealie…", item["name"])
                ok = add_to_mealie_shopping_list(item["name"], MEALIE_SHOPPING_LIST_ID,
                                                 quantity=1.0)
                if not ok:
                    logger.warning("Could not add '%s' to Mealie.", item["name"])

        except requests.RequestException as e:
            logger.error("❌ API request error in main loop: %s", e)

        logger.info("⏳ Waiting %s seconds…\n", INTERVAL)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "health":
        result = health_check()
        if result["status"] == "healthy":
            logger.info("Health check passed: all services operational")
            sys.exit(0)
        else:
            logger.error("Health check failed: one or more services unreachable")
            sys.exit(1)
    else:
        main()
