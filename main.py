import os
import time
import logging
import requests
from typing import Dict, List
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

if not all([GROCY_API_URL, GROCY_API_KEY, MEALIE_BASE_URL, MEALIE_API_KEY, MEALIE_SHOPPING_LIST_ID]):
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
    Returns: { display_lower: {display, foodId, itemId} }
    """
    url = f"{MEALIE_BASE_URL}/api/households/shopping/items"
    result = {}
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
            result[display.lower()] = {
                "display": display,
                "foodId": it.get("foodId") or (it.get("food") or {}).get("id"),
                "itemId": it.get("id")
            }

        if not data.get("next"):
            break
        page += 1

    logger.info("Mealie: %d existing shopping list items found.", len(result))
    return result

def add_to_mealie_shopping_list(item_name: str, shopping_list_id: str, quantity: float = 1.0) -> bool:
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
        else:
            logger.error("Error during POST (%s): %s", resp.status_code, resp.text)
            return False

    except Exception as e:
        logger.error("POST error: %s", e)
        return False

# ------------------------------------------------------------
# Grocy Helper (corrected)
# - Uses pygrocy2 missing_products() / volatile stock helpers
#   instead of own, error-prone product+stock logic
# ------------------------------------------------------------
def get_understock_products() -> List[Dict[str, str]]:
    """
    Returns products that are below minimum stock according to Grocy.
    Uses get_volatile_stock() from pygrocy2.
    Uses only the 'missing_products' list.
    """
    try:
        volatile = grocy.get_volatile_stock()
    except Exception as e:
        logger.error("Error while requesting Grocy volatile stock: %s", e)
        return []

    result = []

    for item in getattr(volatile, "missing_products", []):
        name = getattr(item, "name", None)
        pid = getattr(item, "id", None)

        if name:
            result.append({
                "id": pid,
                "name": name
            })

    logger.info(
        "Grocy: %d products below minimum stock (volatile.missing_products).",
        len(result)
    )

    return result

# ------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------
def main():
    logger.info("🔄 Grocy → Mealie sync started (using pygrocy missing_products)…")

    while True:
        try:
            # Mealie: load existing shopping list entries (prevents duplicates)
            mealie_items = get_mealie_shopping_list_items(MEALIE_SHOPPING_LIST_ID)

            # Grocy: below-minimum-stock products via pygrocy helper
            understock = get_understock_products()
            existing_keys = {k.strip().lower() for k in mealie_items.keys()}
            for item in understock:
                name_key = item.get("name", "").strip().lower()
                if any(name_key in key for key in existing_keys):
                    logger.info("✔ '%s' already in the Mealie list.", item['name'])
                    continue

                logger.info("➕ '%s' will be added to Mealie…", item["name"])
                ok = add_to_mealie_shopping_list(item["name"], MEALIE_SHOPPING_LIST_ID, quantity=1.0)
                if not ok:
                    logger.warning("Could not add '%s' to Mealie.", item["name"])

        except Exception as e:
            logger.exception("❌ Error in main loop: %s", e)

        logger.info("⏳ Waiting %s seconds…\n", INTERVAL)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
