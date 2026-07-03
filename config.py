import os

# API Endpoints
BASE_URL = "https://www.platinumrx.in"
BACKEND_URL = "https://backend.platinumrx.in"
PDP_ENDPOINT = "/medicines/{display_name}/{master_drug_code}"
PRICING_ENDPOINT = "/pdp/fetchDrugPricing"
DELIVERY_ENDPOINT = "/pdp/getEstimatedDeliveryDate"

# Headers (minimum required)
PRICING_HEADERS = {"Content-Type": "application/json"}
DELIVERY_HEADERS = {"Content-Type": "application/json"}

# Pricing request template
PRICING_PAYLOAD_TEMPLATE = {
    "source": "app",
    "fetchOfferPrice": True,
    "fetchDetails": False,
    "fetchBestOfferPrice": True,
}

# Timeouts
REQUEST_TIMEOUT = 30  # seconds

# Retry config
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
