import time
from typing import Any, Dict, List, Optional

import requests

from config import (
    BASE_URL,
    BACKEND_URL,
    DELIVERY_ENDPOINT,
    DELIVERY_HEADERS,
    MAX_RETRIES,
    PDP_ENDPOINT,
    PRICING_ENDPOINT,
    PRICING_HEADERS,
    PRICING_PAYLOAD_TEMPLATE,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
)


class PlatinumRxClient:
    """HTTP client for fetching product data from PlatinumRx.in.

    Provides access to three data sources:
        1. SSR HTML PDP page
        2. Pricing API
        3. Delivery ETA API
    """

    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()

    def fetch_pdp_page(self, display_name: str, master_drug_code: int) -> str:
        """Fetch the full SSR HTML page for a product.

        Parameters
        ----------
        display_name : str
            URL-safe product display name (e.g. "ikvaz-500mg-tablet").
        master_drug_code : int
            Numeric drug identifier (e.g. 1000002).

        Returns
        -------
        str
            Raw HTML content of the PDP page.

        Raises
        ------
        requests.RequestException
            If all retry attempts fail.
        """
        url = f"{BASE_URL}{PDP_ENDPOINT.format(display_name=display_name, master_drug_code=master_drug_code)}"

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAY)

    def fetch_pricing(
        self, drug_code: int, **overrides: Any
    ) -> Dict[str, Any]:
        """Fetch current pricing, stock, and substitute data for a drug.

        Parameters
        ----------
        drug_code : int
            Numeric drug code (matches master_drug_code on PDP).
        **overrides
            Additional payload keys to override PRICING_PAYLOAD_TEMPLATE.

        Returns
        -------
        Dict[str, Any]
            JSON response containing masterCatalogData, substituteCatalogData,
            and priceCalculations.

        Raises
        ------
        requests.RequestException
            If all retry attempts fail.
        """
        url = f"{BACKEND_URL}{PRICING_ENDPOINT}"
        payload = {**PRICING_PAYLOAD_TEMPLATE, "drugCode": drug_code, **overrides}

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.post(
                    url, json=payload, headers=PRICING_HEADERS, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAY)

    def fetch_delivery_eta(
        self, pincode: int, drug_codes: List[int], page: str = "PDP"
    ) -> Dict[str, Any]:
        """Fetch estimated delivery dates for drugs at a given pincode.

        Parameters
        ----------
        pincode : int
            Delivery location pincode.
        drug_codes : List[int]
            One or more drug codes to query delivery for.
        page : str
            Context page identifier (default "PDP").

        Returns
        -------
        Dict[str, Any]
            JSON response with an 'eta' key containing delivery dates.

        Raises
        ------
        requests.RequestException
            If all retry attempts fail.
        """
        url = f"{BACKEND_URL}{DELIVERY_ENDPOINT}"
        payload = {"pincode": pincode, "drugCodes": drug_codes, "page": page}

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.post(
                    url, json=payload, headers=DELIVERY_HEADERS, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(RETRY_DELAY)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> "PlatinumRxClient":
        return self

    def __exit__(self, *exc_args: Any) -> None:
        self.close()
