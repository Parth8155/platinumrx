import argparse
import gzip
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional
import pymysql
from concurrent.futures import ThreadPoolExecutor
from api_client import PlatinumRxClient
from parser import (
    parse_delivery_response,
    parse_pdp_page,
    parse_pricing_response,
    parse_product_url,
    merge_pricing_data,
)

FOLDER_PATH = rf"D:\Manav Mehta\KSDB - platinumrx\Pagesaves"
def make_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='parth123',
        database='ksdb_platinumrx',
    )
def create_table():
    with make_connection() as conn:
        with conn.cursor() as curr:
            curr.execute("""
                CREATE TABLE IF NOT EXISTS pdp_data_2026_07_02 (
                    product_id varchar(128),
                    catalog_name VARCHAR(1024),
                    catalog_id varchar(128),
                    source VARCHAR(16),
                    scraped_date varchar(128),
                    product_name VARCHAR(1024),
                    image_url TEXT,
                    category_hierarchy TEXT,
                    product_price VARCHAR(1024),
                    arrival_date VARCHAR(1024),
                    shipping_charges VARCHAR(128),
                    is_sold_out VARCHAR(8),
                    discount VARCHAR(8),
                    mrp VARCHAR(128),
                    page_url varchar(8),
                    product_url TEXT,
                    number_of_ratings VARCHAR(8),
                    avg_rating VARCHAR(8),
                    position VARCHAR(8),
                    country_code VARCHAR(8),
                    others TEXT
                );
            """)
        conn.commit()
def insert_data(data, product_id):
    with make_connection() as conn:
        with conn.cursor() as curr:
            curr.execute("""
                INSERT INTO pdp_data_2026_07_02 (
                    product_id,
                    catalog_name,
                    catalog_id,
                    source,
                    scraped_date,
                    product_name,
                    image_url,
                    category_hierarchy,
                    product_price,
                    arrival_date,
                    shipping_charges,
                    is_sold_out,
                    discount,
                    mrp,
                    page_url,
                    product_url,
                    number_of_ratings,
                    avg_rating,
                    position,
                    country_code,
                    others
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s
                );
            """, (
                data.get("product_id"),
                data.get("catalog_name"),
                data.get("catalog_id"),
                data.get("source"),
                data.get("scraped_date"),
                data.get("product_name"),
                data.get("image_url"),
                json.dumps(data.get("category_hierarchy")),
                data.get("product_price"),
                data.get("arrival_date"),
                data.get("shipping_charges"),
                data.get("is_sold_out"),
                data.get("discount"),
                data.get("mrp"),
                data.get("page_url"),
                data.get("product_url"),
                data.get("number_of_ratings"),
                data.get("avg_rating"),
                data.get("position"),
                data.get("country_code"),
                json.dumps(data.get("others"))
            ))
            # curr.execute("UPDATE sitemap_2026_07_02 set status='fetched' where product_id=%s", (product_id,))
            conn.commit()
def readFileFunc(filePath):
    with gzip.open(filePath, 'rb') as file:
        content = file.read()
        content_str = content.decode('utf-8')
        return content_str

def format_product_output(
    result: Dict[str, Any],
    master_drug_code: int,
) -> Dict[str, Any]:
    basic_info = result.get("basic_info", {}) or {}
    pricing = result.get("pricing", {}) or {}
    availability = result.get("availability", {}) or {}
    delivery_eta = result.get("delivery_eta", {}) or {}
    breadcrumbs = result.get("breadcrumbs", []) or []

    product_name = (
        basic_info.get("product_name")
        or basic_info.get("display_name")
        or basic_info.get("sku_name")
        or ""
    )
    image_url = (
        basic_info.get("image")
        or basic_info.get("hero_image")
        or ""
    )
    product_url = basic_info.get("product_url") or ""
    if not product_url:
        bc_urls = [b.get("url", "") for b in breadcrumbs if isinstance(b, dict) and b.get("url")]
        product_url = bc_urls[-1] if bc_urls else ""
    product_price = pricing.get("offer_price") or pricing.get("discounted_price")

    bc_names = [b.get("name", "") for b in breadcrumbs if isinstance(b, dict)]
    ch_dict = {}
    for i, name in enumerate(bc_names[:-1], start=1):
        if name:
            ch_dict[f"l{i}"] = name
    category_hierarchy = ch_dict if ch_dict else ""

    is_sold_out = availability.get("banned", False) or availability.get("drug_stock", 1) == 0

    discount_raw = pricing.get("discount_percentage")
    discount_val = "N/A" if discount_raw is None or str(discount_raw) in ("0", "0.0", "0.00") else discount_raw

    others = dict(result)
    if not others.get("substitute"):
        others.pop("substitute", None)
    others.pop("breadcrumbs", None)
    others.pop("pricing", None)
    others.pop("delivery_eta", None)
    others.pop("category_hierarchy", None)
    bi = others.pop("basic_info", None)
    if isinstance(bi, dict):
        others.update(bi)
    others.pop("product_url", None)
    dd = others.pop("detailed_description", None)
    if isinstance(dd, dict):
        dd.pop("FAQ", None)
        others.update(dd)

    mfr = others.get("manufacturer_info")
    if isinstance(mfr, dict):
        for key in ( "brand_name", "manufacturer_legal_name", "manufacturer_name_rsc"):
            mfr.pop(key, None)
        if not mfr:
            others.pop("manufacturer_info", None)
    substitute = result.get("substitute") or {}        
    if substitute :
        sub_code = substitute.get("drug_code") or pricing.get("substitute_drug_code")
        others["variation_id"] = [sub_code] if sub_code is not None else []
    others["MOQ"] = "1"
    others["data_vendor"] = "Actowiz"
    mfr_info = result.get("manufacturer_info", {}) or {}
    brand_val = mfr_info.get("brand_name") or mfr_info.get("manufacturer_name") or ""
    if not brand_val:
        pn = basic_info.get("product_name", "")
        brand_val = pn.split()[0] if pn else ""
    others["brand"] = brand_val

    # images = []
    # for img_key in ("image", "hero_image"):
    #     val = basic_info.get(img_key)
    #     if val:
    #         images.append(val)
    # img_list = basic_info.get("image_list")
    # if isinstance(img_list, list):
    #     for url in img_list:
    #         if url and url not in images:
    #             images.append(url)
    # elif isinstance(img_list, str) and img_list.strip():
    #     urls = [u.strip() for u in img_list.split(",") if u.strip()]
    #     for url in urls:
    #         if url not in images:
    #             images.append(url)
    # others["Images"] = images

    if substitute:
        sub_images = []
        for img_key in ("image", "hero_image"):
            val = substitute.get(img_key)
            if val and val not in sub_images:
                sub_images.append(val)
        sub_img_list = substitute.get("image_list")
        if isinstance(sub_img_list, list):
            for url in sub_img_list:
                if url and url not in sub_images:
                    sub_images.append(url)
        elif isinstance(sub_img_list, str) and sub_img_list.strip():
            urls = [u.strip() for u in sub_img_list.split(",") if u.strip()]
            for url in urls:
                if url not in sub_images:
                    sub_images.append(url)
    # if sub_images:
    #     others.setdefault("substitute", {})["img"] = sub_images
    shipping_charges = "N/A"
    if not is_sold_out:
        shipping_charges = {"Delivery Fee": '0' if float(product_price) > 500 else '49',
                            "Handling & Packaging Fee":"9"}

    return {
        "product_id": master_drug_code,
        "catalog_name": product_name,
        "catalog_id": master_drug_code,
        "source": "platinumrx",
        "scraped_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "product_name": product_name,
        "image_url": image_url,
        "category_hierarchy": category_hierarchy,
        "product_price": product_price,
        "arrival_date": delivery_eta.get("max_eta"),
        "shipping_charges": shipping_charges,
        "is_sold_out": is_sold_out,
        "discount": discount_val,
        "mrp": pricing.get("mrp"),
        "page_url": "N/A",
        "product_url": product_url,
        "number_of_ratings": "N/A",
        "avg_rating": "N/A",
        "position": "N/A",
        "country_code": "IN",
        "others": others,
    }


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

def pagesave(foldPath, fileName, response):
    filePath = os.path.join(foldPath, fileName)
    if not os.path.exists(foldPath):
        os.makedirs(foldPath)
    try:
        with gzip.open(filePath, 'wb') as file:
            file.write(response.encode())
        return True
    except Exception as e:
        print(f"[{fileName}] [{foldPath}] Error saving")
        return False

def save_page_artifacts(
    display_name: str,
    master_drug_code: int,
    html: str,
    pricing_response: Optional[Dict] = None,
    delivery_response: Optional[Dict] = None,
    pincode: Optional[int] = None,
) -> str:
    base = f"{master_drug_code}"

    # html_dir = os.path.join(FOLDER_PATH, "html")
    # os.makedirs(html_dir, exist_ok=True)
    # html_path = os.path.join(html_dir, f"{base}.html")
    # with open(html_path, "w", encoding="utf-8") as f:
    #     f.write(html)
    # print(f"  [save] {html_path}")

    if pricing_response:
        pricing_dir = os.path.join(FOLDER_PATH, "pricing")
        pagesave(foldPath=pricing_dir, fileName=f"{base}.html.gz", response=json.dumps(pricing_response))

    if delivery_response and pincode:
        delivery_dir = os.path.join(FOLDER_PATH, "delivery")
        pagesave(foldPath=delivery_dir, fileName=f"{base}.html.gz", response=json.dumps(pricing_response))

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
        sub = result.get(sub_key)
        
        if sub is not None:
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

    return format_product_output(result, master_drug_code)


def write_output(data: Dict[str, Any], output_path: Optional[str]) -> None:
    output = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Data saved to {output_path}")
    else:
        print(output)


# def main() -> None:
#     parser = argparse.ArgumentParser(description="PlatinumRx PDP Scraper")
#     group = parser.add_mutually_exclusive_group(required=True)
#     group.add_argument("--url", help="Full PDP URL to scrape")
#     group.add_argument("--code", type=int, help="Master drug code")
#     parser.add_argument("--name", help="Display name (used with --code)")
#     parser.add_argument("--output", help="Output file path (default: stdout)")
#     parser.add_argument("--pincode", type=int, help="Pincode for delivery ETA")
#     args = parser.parse_args()

#     validate_args(args)

#     client = PlatinumRxClient()
#     try:
#         product_data = build_output(args, client)
#         write_output(product_data, args.output)
#     except Exception as e:
#         print(f"Error: {e}", file=sys.stderr)
#         sys.exit(1)
#     finally:
#         client.close()

def start_work(data):
    args = argparse.Namespace(
        url=data["product_url"],
        code=None,
        name=None,
        pincode=560001,
    )
    validate_args(args)
    client = PlatinumRxClient()
    try:
        product_data = build_output(args, client)
        insert_data(product_data, data['product_id'])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
            client.close()

def main() -> None:
    create_table()
    with make_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as curr:
            curr.execute("SELECT * from sitemap_2026_07_02 where status='done' limit 1")
            # curr.execute("SELECT * from sitemap_2026_07_02 where product_id='1000006'")
            datas = curr.fetchall()
            with ThreadPoolExecutor(max_workers=8) as executor:
                executor.map(start_work, datas)


if __name__ == "__main__":
    # main("https://www.platinumrx.in/medicines/rabceaz-d-10mg-20mg-tablet/1000001", 560001,'output.json')
    main()
    # main()
    # start_work({"product_url": "https://www.platinumrx.in/medicines/rabceaz-d-10mg-20mg-tablet/1000001", "product_id": 1000001})