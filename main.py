import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from api_client import PlatinumRxClient
from parser import (
    parse_delivery_response,
    parse_pdp_page,
    parse_pricing_response,
    parse_product_url,
    merge_pricing_data,
)


def resolve_identifiers(
    url: Optional[str], code: Optional[int], name: Optional[str]
) -> tuple[Optional[str], Optional[int]]:
    if url:
        return parse_product_url(url)
    return name, code


def validate_args(args: argparse.Namespace) -> None:
    if args.code and not args.name:
        print("Error: --name is required when --code is provided", file=sys.stderr)
        sys.exit(1)


def save_page_artifacts(
    display_name: str,
    master_drug_code: int,
    html: str,
    pricing_response: Optional[Dict] = None,
    delivery_response: Optional[Dict] = None,
    pincode: Optional[int] = None,
) -> str:
    base = f"{display_name}_{master_drug_code}"

    html_dir = os.path.join("pagesaves", "html")
    os.makedirs(html_dir, exist_ok=True)
    html_path = os.path.join(html_dir, f"{base}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [save] {html_path}")

    if pricing_response:
        pricing_dir = os.path.join("pagesaves", "pricing")
        os.makedirs(pricing_dir, exist_ok=True)
        pricing_path = os.path.join(pricing_dir, f"{base}.json")
        with open(pricing_path, "w", encoding="utf-8") as f:
            json.dump(pricing_response, f, indent=2, ensure_ascii=False)
        print(f"  [save] {pricing_path}")

    if delivery_response and pincode:
        delivery_dir = os.path.join("pagesaves", "delivery")
        os.makedirs(delivery_dir, exist_ok=True)
        delivery_name = f"{base}_{pincode}.json"
        delivery_path = os.path.join(delivery_dir, delivery_name)
        with open(delivery_path, "w", encoding="utf-8") as f:
            json.dump(delivery_response, f, indent=2, ensure_ascii=False)
        print(f"  [save] {delivery_path}")

    return base


def build_output(args: argparse.Namespace, client: PlatinumRxClient) -> Dict[str, Any]:
    display_name, master_drug_code = resolve_identifiers(
        args.url, args.code, args.name
    )

    if not display_name or not master_drug_code:
        print("Error: Could not determine product identifiers", file=sys.stderr)
        sys.exit(1)

    html = client.fetch_pdp_page(display_name, master_drug_code)

    api_pricing = client.fetch_pricing(master_drug_code)

    eta_response = None
    if args.pincode:
        drug_codes = [master_drug_code]
        eta_response = client.fetch_delivery_eta(args.pincode, drug_codes)

    save_page_artifacts(
        display_name=display_name,
        master_drug_code=master_drug_code,
        html=html,
        pricing_response=api_pricing,
        delivery_response=eta_response,
        pincode=args.pincode,
    )

    result = parse_pdp_page(html)
    parsed_api_pricing = parse_pricing_response(api_pricing)
    result["pricing"] = merge_pricing_data(result.get("pricing", {}), parsed_api_pricing)

    sub_key = "substitute"
    if parsed_api_pricing.get("substitute_drug_code"):
        sub = result.setdefault(sub_key, {})
        if "drug_code" not in sub:
            sub["drug_code"] = parsed_api_pricing["substitute_drug_code"]
        for src_key, dst_key in [
            ("substitute_mrp", "mrp"),
            ("substitute_discounted_price", "discounted_price"),
            ("substitute_offer_price", "offer_price"),
            ("substitute_drug_stock", "drug_stock"),
            ("substitute_banned", "banned"),
        ]:
            if src_key in parsed_api_pricing and dst_key not in sub:
                sub[dst_key] = parsed_api_pricing[src_key]

    if args.pincode and eta_response:
        result["delivery_eta"] = parse_delivery_response(eta_response)

    return result


def write_output(data: Dict[str, Any], output_path: Optional[str]) -> None:
    output = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Data saved to {output_path}")
    else:
        print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="PlatinumRx PDP Scraper")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="Full PDP URL to scrape")
    group.add_argument("--code", type=int, help="Master drug code")
    parser.add_argument("--name", help="Display name (used with --code)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--pincode", type=int, help="Pincode for delivery ETA")
    args = parser.parse_args()

    validate_args(args)

    client = PlatinumRxClient()
    try:
        product_data = build_output(args, client)
        write_output(product_data, args.output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
