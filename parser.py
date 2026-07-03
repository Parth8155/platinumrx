import re
import json
from bs4 import BeautifulSoup, Tag
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse


# ── JSON-LD helpers ──────────────────────────────────────────────────

def extract_json_ld(html: str) -> List[Dict[str, Any]]:
    blocks = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    result = []
    for block in blocks:
        try:
            data = json.loads(block)
            result.append(data)
        except json.JSONDecodeError:
            continue
    return result


def extract_ld_by_type(html: str, ld_type: str) -> Optional[Dict[str, Any]]:
    blocks = extract_json_ld(html)
    for block in blocks:
        if block.get("@type") == ld_type:
            return block
    return None


# ── RSC payload parsing ──────────────────────────────────────────────

def _unescape_rsc(text: str) -> str:
    return text.encode("utf-8").decode("unicode_escape")


def _find_rsc_objects(html: str) -> Dict[str, Any]:
    blocks = re.findall(
        r'self\.__next_f\.push\(\[1,"(.*?)"\]\)',
        html, re.DOTALL
    )
    if not blocks:
        return {}
    joined = "".join(blocks)
    unescaped = _unescape_rsc(joined)

    objects = {}
    for m in re.finditer(r"(?:^|\n)([0-9a-fA-F]+):", unescaped):
        num = m.group(1)
        start = m.end()
        if start >= len(unescaped):
            continue
        ch = unescaped[start]
        if ch == "{":
            depth = 0
            end = start
            in_string = False
            escape = False
            while end < len(unescaped):
                ch2 = unescaped[end]
                if escape:
                    escape = False
                elif ch2 == "\\":
                    escape = True
                elif ch2 == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch2 == "{":
                        depth += 1
                    elif ch2 == "}":
                        depth -= 1
                        if depth == 0:
                            end += 1
                            break
                end += 1
            if depth == 0:
                json_str = unescaped[start:end]
                try:
                    data = json.loads(json_str)
                    objects[num] = data
                except json.JSONDecodeError:
                    pass
        elif ch == "[":
            depth = 0
            end = start
            in_string = False
            escape = False
            while end < len(unescaped):
                ch2 = unescaped[end]
                if escape:
                    escape = False
                elif ch2 == "\\":
                    escape = True
                elif ch2 == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch2 == "[":
                        depth += 1
                    elif ch2 == "]":
                        depth -= 1
                        if depth == 0:
                            end += 1
                            break
                end += 1
            if depth == 0:
                json_str = unescaped[start:end]
                try:
                    data = json.loads(json_str)
                    objects[num] = data
                except json.JSONDecodeError:
                    pass
        else:
            val = unescaped[start:].split("\n")[0].strip()
            try:
                objects[num] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                pass
    return objects


def _resolve_refs(obj: Any, objects: Dict[str, Any], visited: Optional[set] = None) -> Any:
    if visited is None:
        visited = set()
    if isinstance(obj, str) and obj.startswith("$"):
        ref = obj[1:]
        if ref in visited:
            return obj
        if ref in objects:
            visited.add(ref)
            return _resolve_refs(objects[ref], objects, visited)
        return obj
    if isinstance(obj, dict):
        return {k: _resolve_refs(v, objects, visited) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_refs(v, objects, visited) for v in obj]
    return obj


KNOWN_PRODUCT_FIELDS = {
    "masterDrugCode", "skuName", "displayName", "urlName",
    "saltComposition", "manufacturerName", "manufacturerAddress",
    "packForm", "drugForm", "packQuantityValueDecimal",
    "drugCategory", "therapeuticClass", "heroImage",
    "dosage", "storageInfo", "primaryUses",
    "sideEffectsSummary", "commonSideEffects",
    "directionsToUse", "howDrugWorks",
    "whatIfMissed", "quickTips",
}


def extract_rsc_product_data(html: str) -> Dict[str, Any]:
    objects = _find_rsc_objects(html)
    if not objects:
        return {}

    resolved_all = {}
    for oid, obj in objects.items():
        resolved_all[oid] = _resolve_refs(obj, objects)

    candidates = []
    for oid, obj in resolved_all.items():
        if isinstance(obj, dict):
            score = sum(1 for k in obj if k in KNOWN_PRODUCT_FIELDS)
            if score >= 3:
                candidates.append((score, oid, obj))

    candidates.sort(key=lambda x: -x[0])

    result = {}
    for score, oid, obj in candidates:
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("$"):
                continue
            if k not in result:
                result[k] = v

    return result


# ── Dynamic section extraction ───────────────────────────────────────

def _extract_fact_row(row: Tag) -> Optional[Dict[str, str]]:
    cells = row.find_all(["td", "th", "div", "span", "p"], recursive=False)
    texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
    if len(texts) >= 2:
        return {texts[0]: texts[1]}
    elif len(texts) == 1:
        return {"label": texts[0]}
    return None


def _extract_nested_content(container: Tag) -> List[Any]:
    items = []
    for child in container.children:
        if not isinstance(child, Tag):
            continue
        if child.get("role") == "separator":
            continue
        tag = child.name
        if tag == "ul":
            lis = child.find_all("li", recursive=True)
            for li in lis:
                t = li.get_text(strip=True)
                if t:
                    items.append(t)
        elif tag == "ol":
            lis = child.find_all("li", recursive=True)
            for li in lis:
                t = li.get_text(strip=True)
                if t:
                    items.append(t)
        elif tag == "p":
            t = child.get_text(strip=True)
            if t:
                items.append(t)
        elif tag == "div":
            inner = child.get_text(strip=True)
            if inner:
                sub_items = _extract_nested_content(child)
                if sub_items:
                    items.extend(sub_items)
                else:
                    items.append(inner)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue
    return items


def _get_content_container(section_div: Tag) -> Optional[Tag]:
    content_div = section_div.find(lambda t: t.get("data-slot") == "section-content")
    if content_div:
        return content_div
    anchor = section_div.find(lambda t: t.get("data-slot") == "section-anchor")
    if anchor:
        return anchor
    return section_div


def extract_descriptive_sections(html: str) -> Dict[str, List[Any]]:
    soup = BeautifulSoup(html, "html.parser")
    sections = {}

    section_divs = soup.find_all("div", attrs={"data-slot": True})
    top_level = []
    for div in section_divs:
        slot = div.get("data-slot", "")
        if slot.startswith("section-") and slot not in ("section-anchor", "section-title", "section-content"):
            parent_section = div.find_parent(lambda t: isinstance(t, Tag) and
                                              t.get("data-slot", "").startswith("section-") and
                                              t.get("data-slot", "") not in ("section-anchor", "section-title", "section-content") and
                                              t != div)
            if not parent_section:
                top_level.append(div)

    for section_div in top_level:
        title_elem = section_div.find(lambda t: t.get("data-slot") == "section-title")
        if not title_elem:
            continue
        heading = title_elem.get_text(strip=True)
        if not heading:
            continue

        slot = section_div.get("data-slot", "")

        # ── Special: Safety Advice cards ──────────────────────────
        safety_cards = section_div.find_all(lambda t: t.get("data-testid", "").startswith("pdp-safety-item-"))
        if safety_cards:
            items = []
            for card in safety_cards:
                h5s = card.find_all("h5")
                card_title = h5s[0].get_text(strip=True) if len(h5s) > 0 else ""
                card_severity = h5s[1].get_text(strip=True) if len(h5s) > 1 else ""
                card_desc_p = card.find("p")
                card_desc = card_desc_p.get_text(strip=True) if card_desc_p else ""
                parts = [p for p in [card_title, card_severity, card_desc] if p]
                if parts:
                    items.append(": ".join(parts))
            if items:
                sections[heading] = items
            continue

        # ── Special: Fact Box ──────────────────────────────────────
        if slot == "section-fact-box":
            fact_rows = section_div.find_all(
                lambda t: t.get("data-testid", "").startswith("pdp-fact-box-row-")
            )
            if fact_rows:
                items = []
                for row in fact_rows:
                    kv = _extract_fact_row(row)
                    if kv:
                        items.append(kv)
                if items:
                    sections[heading] = items
                continue

        # ── Special: FAQ ───────────────────────────────────────────
        if slot == "section-faqs":
            ld_faq = extract_ld_by_type(html, "FAQPage")
            if ld_faq:
                main_entity = ld_faq.get("mainEntity", [])
                if isinstance(main_entity, list):
                    qa_list = []
                    for item in main_entity:
                        if isinstance(item, dict):
                            q = item.get("name", "").strip()
                            answer_obj = item.get("acceptedAnswer", {})
                            a = answer_obj.get("text", "").strip() if isinstance(answer_obj, dict) else ""
                            if q or a:
                                qa_list.append({"question": q, "answer": a})
                    if qa_list:
                        sections[heading] = qa_list
                        continue
            faq_items = section_div.find_all(lambda t: t.get("data-slot") == "accordion-item")
            if faq_items:
                qa_list = []
                for faq in faq_items:
                    trigger = faq.find(lambda t: t.get("data-testid", "").startswith("pdp-faq-trigger-"))
                    question = trigger.get_text(strip=True) if trigger else ""
                    answer = faq.get_text(strip=True)
                    if question or answer:
                        qa_list.append({"question": question, "answer": answer})
                if qa_list:
                    sections[heading] = qa_list
                continue

        # ── Regular: find content container and extract ──────────
        content_container = _get_content_container(section_div)
        if content_container:
            content_items = _extract_nested_content(content_container)
            if content_items:
                if heading in sections:
                    sections[heading].extend(content_items)
                else:
                    sections[heading] = content_items

    # Also extract hero sections that appear before the description
    hero_data = {}
    hero_title = soup.find(lambda t: t.get("data-testid") == "pdp-hero-product-title")
    if hero_title:
        hero_data["Product Title"] = [hero_title.get_text(strip=True)]
    hero_salt = soup.find(lambda t: t.get("data-testid") == "pdp-hero-salt-composition")
    if hero_salt:
        hero_data["Salt Composition"] = [hero_salt.get_text(strip=True)]
    hero_summary = soup.find(lambda t: t.get("data-testid") == "pdp-hero-quick-summary")
    if hero_summary:
        hero_data["Quick Summary"] = [hero_summary.get_text(strip=True)]

    merged = {}
    for k, v in hero_data.items():
        merged[k] = v
    for k, v in sections.items():
        if k not in merged:
            merged[k] = v

    disclaimer_elem = soup.find(lambda t: t.name and t.get_text(strip=True).startswith("Disclaimer"))
    if disclaimer_elem:
        parent_section = disclaimer_elem.find_parent(lambda t: isinstance(t, Tag) and t.get("data-slot", "").startswith("section-"))
        if parent_section:
            content = _get_content_container(parent_section)
            if content:
                merged["Disclaimer"] = _extract_nested_content(content)
        if "Disclaimer" not in merged:
            txt = disclaimer_elem.get_text(strip=True)
            if txt:
                merged["Disclaimer"] = [txt]

    return merged


def extract_breadcrumbs(html: str) -> List[Dict[str, str]]:
    ld = extract_ld_by_type(html, "BreadcrumbList")
    if ld:
        items = ld.get("itemListElement", [])
        return [
            {"name": item.get("name"), "url": item.get("item")}
            for item in items if isinstance(item, dict)
        ]
    soup = BeautifulSoup(html, "html.parser")
    breadcrumb_items = soup.find_all(lambda t: t.get("data-testid") == "breadcrumb-item")
    result = []
    for item in breadcrumb_items:
        link = item.find("a")
        if link:
            result.append({"name": link.get_text(strip=True), "url": link.get("href", "")})
    return result


def extract_faq_list(html: str) -> List[Dict[str, str]]:
    ld = extract_ld_by_type(html, "FAQPage")
    if ld:
        main_entity = ld.get("mainEntity", [])
        if isinstance(main_entity, list):
            faqs = []
            for item in main_entity:
                if isinstance(item, dict):
                    q = item.get("name", "").strip()
                    answer_obj = item.get("acceptedAnswer", {})
                    a = answer_obj.get("text", "").strip() if isinstance(answer_obj, dict) else ""
                    faqs.append({"question": q, "answer": a})
            return faqs
    return []


# ── Product data extraction ──────────────────────────────────────────

def extract_drug_ld(html: str) -> Dict[str, Any]:
    return extract_ld_by_type(html, "Drug") or {}


def extract_product_ld(html: str) -> Dict[str, Any]:
    return extract_ld_by_type(html, "Product") or {}


def extract_comparison_table(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(lambda t: t.get("data-testid") == "pdp-info-comparison-table")
    if not table:
        return {"exact_match": "", "current_product": {}, "substitute_product": {}}

    exact_match_div = table.find("div", string=re.compile(r"Exact Salt Match|Exact Match", re.IGNORECASE))
    exact_match = exact_match_div.get_text(strip=True) if exact_match_div else ""

    grids = table.find_all("div", class_=lambda c: c and "grid-cols-2" in c)

    current_product = {}
    substitute_product = {}

    for grid in grids:
        cells = grid.find_all("div", recursive=False)
        if len(cells) < 2:
            continue
        left = cells[0].get_text(strip=True)
        right = cells[1].get_text(strip=True)
        if not left and not right:
            continue

        has_salt_link = bool(cells[0].find("a", href=re.compile(r"/salt/")))
        has_brand_link = bool(cells[0].find("a", href=re.compile(r"/brands/")))
        is_header = bool(cells[0].find("div", class_=lambda c: c and "line-clamp-2" in c))

        if is_header:
            if left:
                current_product["name"] = left
            if right:
                substitute_product["name"] = right
            continue
        if has_salt_link:
            current_product["salt"] = left
            substitute_product["salt"] = right
            continue
        if has_brand_link:
            current_product["manufacturer"] = left
            substitute_product["manufacturer"] = right
            continue
        if "Approved" in left or "Approved" in right:
            key = left.replace(" ", "_").lower()
            current_product[key] = left
            substitute_product[key] = right
            continue
        if "₹" in left or "₹" in right:
            current_product["price_per_unit"] = left
            substitute_product["price_per_unit"] = right
            continue

    return {
        "exact_match": exact_match,
        "current_product": current_product,
        "substitute_product": substitute_product,
    }


def parse_pdp_page(html: str) -> Dict[str, Any]:
    drug_ld = extract_drug_ld(html)
    product_ld = extract_product_ld(html)
    rsc = extract_rsc_product_data(html)

    product_name = (
        product_ld.get("name")
        or rsc.get("displayName")
        or drug_ld.get("name")
        or ""
    )

    breadcrumbs = extract_breadcrumbs(html)

    basic_info = {}
    if drug_ld:
        basic_info["prescription_status"] = drug_ld.get("prescriptionStatus")
        basic_info["active_ingredient"] = drug_ld.get("activeIngredient")
        basic_info["dosage_form"] = drug_ld.get("dosageForm")
    if product_ld:
        basic_info["product_name"] = product_ld.get("name")
        basic_info["sku"] = product_ld.get("sku")
        basic_info["image"] = product_ld.get("image")
        basic_info["product_url"] = product_ld.get("url")
    if rsc:
        basic_info["display_name"] = rsc.get("displayName")
        basic_info["sku_name"] = rsc.get("skuName")
        basic_info["url_name"] = rsc.get("urlName")
        basic_info["salt_composition"] = rsc.get("saltComposition")
        basic_info["drug_form"] = rsc.get("drugForm")
        basic_info["pack_form"] = rsc.get("packForm")
        basic_info["pack_quantity"] = rsc.get("packQuantityValueDecimal")
        basic_info["unit_of_measurement"] = rsc.get("unitOfMeasurement")
        basic_info["drug_category"] = rsc.get("drugCategory")
        basic_info["ailment"] = rsc.get("ailment")
        basic_info["ailment_type"] = rsc.get("ailmentType")
        basic_info["therapeutic_class"] = rsc.get("therapeuticClass")
        basic_info["hero_image"] = rsc.get("heroImage")
        basic_info["image_list"] = rsc.get("imageList")
        basic_info["pdp_id"] = rsc.get("pdpId")
        basic_info["pdp_data_id"] = rsc.get("id")
    basic_info = {k: v for k, v in basic_info.items() if v is not None}

    medicine_comparison = extract_comparison_table(html)
    if not medicine_comparison.get("current_product"):
        cp = {}
        sp = {}
        if rsc:
            cp["salt_composition"] = rsc.get("saltComposition")
            cp["salt_id"] = rsc.get("saltId")
            cp["therapeutic_class"] = rsc.get("therapeuticClass")
            cp["sku_category_type"] = rsc.get("skuCategoryType")
            cp["generic"] = rsc.get("generic")
            cp["hsn_code"] = rsc.get("hsnCode")
            cp["name"] = rsc.get("displayName")
            cp["manufacturer"] = rsc.get("manufacturerName")
            cp["mrp"] = rsc.get("mrp")
            cp["drug_form"] = rsc.get("drugForm")
            cp["pack_form"] = rsc.get("packForm")
            cp["pack_quantity"] = rsc.get("packQuantityValueDecimal")
        if drug_ld:
            cp["non_proprietary_name"] = drug_ld.get("nonProprietaryName")
            cp["is_available_generically"] = drug_ld.get("isAvailableGenerically")
            cp["is_proprietary"] = drug_ld.get("isProprietary")
            cp["proprietary_name"] = drug_ld.get("proprietaryName")
            cp["drug_unit"] = drug_ld.get("drugUnit")
            cp["active_ingredient"] = drug_ld.get("activeIngredient")
        sub_keys = {k.split("sub_", 1)[1]: v for k, v in rsc.items() if k.startswith("sub_")}
        if sub_keys:
            sp["name"] = sub_keys.get("displayName")
            sp["salt_composition"] = sub_keys.get("saltComposition")
            sp["manufacturer"] = sub_keys.get("manufacturerName")
            sp["mrp"] = sub_keys.get("mrp")
            sp["drug_form"] = sub_keys.get("drugForm")
            sp["pack_form"] = sub_keys.get("packForm")
            sp["drug_code"] = sub_keys.get("masterDrugCode")
        medicine_comparison = {
            "exact_match": "",
            "current_product": {k: v for k, v in cp.items() if v is not None},
            "substitute_product": {k: v for k, v in sp.items() if v is not None},
        }

    manufacturer_info = {}
    if product_ld:
        brand = product_ld.get("brand", {})
        if isinstance(brand, dict):
            manufacturer_info["brand_name"] = brand.get("name")
        mfr_ld = product_ld.get("manufacturer", {})
        if isinstance(mfr_ld, dict):
            manufacturer_info["manufacturer_name"] = mfr_ld.get("name")
    if drug_ld:
        mfr_drug = drug_ld.get("manufacturer", {})
        if isinstance(mfr_drug, dict):
            manufacturer_info["manufacturer_legal_name"] = mfr_drug.get("legalName")
    if rsc:
        manufacturer_info["manufacturer_name_rsc"] = rsc.get("manufacturerName")
        manufacturer_info["manufacturer_address"] = rsc.get("manufacturerAddress")
        manufacturer_info["manufacturer_id"] = rsc.get("manufacturerId")
    manufacturer_info = {k: v for k, v in manufacturer_info.items() if v is not None}

    pricing = {}
    offers_drug = drug_ld.get("offers", {}) if isinstance(drug_ld.get("offers"), dict) else {}
    offers_product = product_ld.get("offers", {}) if isinstance(product_ld.get("offers"), dict) else {}
    offers = offers_drug or offers_product
    if offers:
        pricing["mrp"] = offers.get("price")
        pricing["currency"] = offers.get("priceCurrency")
        pricing["availability_status"] = offers.get("availability")
    if rsc:
        pricing["mrp_rsc"] = rsc.get("mrp")
        pricing["discounted_price"] = rsc.get("discountedPrice")
        pricing["offer_price"] = rsc.get("offerPrice")
        pricing["discount_percentage"] = rsc.get("discountPercentage")
        pricing["calculated_per_pack"] = rsc.get("calculatedPerPack")
        pricing["calculated_per_pack_branded"] = rsc.get("calculatedPerPackBranded")
    pricing = {k: v for k, v in pricing.items() if v is not None}

    availability = {}
    if rsc:
        availability["drug_stock"] = rsc.get("drugStock")
        availability["banned"] = rsc.get("banned")
        availability["max_permissible_quantity"] = rsc.get("maxPermissableQuantity")
        availability["cold_storage"] = rsc.get("coldStorage")
        availability["floor_quantity"] = rsc.get("floorQuantity")
    availability = {k: v for k, v in availability.items() if v is not None}

    substitute = {}
    similar = product_ld.get("isSimilarTo") if isinstance(product_ld.get("isSimilarTo"), dict) else None
    if similar:
        substitute["name"] = similar.get("name")
        substitute["url"] = similar.get("url")
        substitute["image"] = similar.get("image")
        sub_brand = similar.get("brand", {})
        if isinstance(sub_brand, dict):
            substitute["brand_name"] = sub_brand.get("name")
        sub_offers = similar.get("offers", {})
        if isinstance(sub_offers, dict):
            substitute["price"] = sub_offers.get("price")
    sub_rsc_keys = {k: v for k, v in rsc.items() if k.startswith("sub_")}
    if sub_rsc_keys:
        substitute["drug_code"] = sub_rsc_keys.get("sub_drugCode")
        substitute["mrp"] = sub_rsc_keys.get("sub_mrp")
        substitute["discounted_price"] = sub_rsc_keys.get("sub_discountedPrice")
        substitute["offer_price"] = sub_rsc_keys.get("sub_offerPrice")
        substitute["drug_stock"] = sub_rsc_keys.get("sub_drugStock")
        substitute["banned"] = sub_rsc_keys.get("sub_banned")
    substitute = {k: v for k, v in substitute.items() if v is not None}

    detailed_description = extract_descriptive_sections(html)

    return {
        "breadcrumbs": breadcrumbs,
        "basic_info": basic_info,
        "medicine_comparison": medicine_comparison,
        "manufacturer_info": manufacturer_info,
        "pricing": pricing,
        "availability": availability,
        "substitute": substitute,
        "detailed_description": detailed_description,
    }


# ── API response parsers ─────────────────────────────────────────────

def parse_pricing_response(data: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    if not data or not isinstance(data, dict):
        return result

    master = data.get("data", {}).get("masterCatalogData", {})
    if isinstance(master, dict):
        result["drug_code"] = master.get("drugCode")
        result["mrp"] = master.get("mrp")
        result["discounted_price"] = master.get("discountedPrice")
        result["offer_price"] = master.get("offerPrice")
        result["upsell_discounted_price"] = master.get("upsellDiscountedPrice")
        result["floor_quantity"] = master.get("floorQuantity")
        result["drug_stock"] = master.get("drugStock")
        result["banned"] = master.get("banned")
        result["max_permissible_quantity"] = master.get("maxPermissableQuantity")

    substitute = data.get("data", {}).get("substituteCatalogData", {})
    if isinstance(substitute, dict):
        result["substitute_drug_code"] = substitute.get("drugCode")
        result["substitute_mrp"] = substitute.get("mrp")
        result["substitute_discounted_price"] = substitute.get("discountedPrice")
        result["substitute_offer_price"] = substitute.get("offerPrice")
        result["substitute_drug_stock"] = substitute.get("drugStock")
        result["substitute_banned"] = substitute.get("banned")

    calc = data.get("data", {}).get("priceCalculations", {})
    if isinstance(calc, dict):
        result["calculated_per_pack"] = calc.get("calculatedPerPack")
        result["calculated_per_pack_branded"] = calc.get("calculatedPerPackBranded")
        result["discount_percentage"] = calc.get("discountPercentage")
        result["annual_savings"] = calc.get("annualSavings")

    best_price = data.get("data", {}).get("bestPriceInfo")
    if best_price is not None:
        result["best_price_info"] = best_price

    return {k: v for k, v in result.items() if v is not None}


def parse_delivery_response(data: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    if not data or not isinstance(data, dict):
        return result

    eta = data.get("eta", {}) if isinstance(data.get("eta"), dict) else {}
    result["min_eta"] = eta.get("minEta")
    result["max_eta"] = eta.get("maxEta")
    result["min_eta_display"] = eta.get("minEtaDisplay")
    result["max_eta_display"] = eta.get("maxEtaDisplay")
    result["cold_chain"] = data.get("coldChain")
    result["cold_chain_serviceable"] = data.get("coldChainServiceable")
    result["pincode_serviceable"] = data.get("pincodeServicable")

    return {k: v for k, v in result.items() if v is not None}


def parse_product_url(url: str) -> Tuple[Optional[str], Optional[int]]:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    parts = path.split("/")
    if len(parts) >= 4 and parts[-2] and parts[-1].isdigit():
        return parts[-2], int(parts[-1])
    if len(parts) >= 3 and parts[-1].isdigit():
        return parts[-2], int(parts[-1])
    return None, None


def merge_pricing_data(base_pricing: Dict[str, Any], api_pricing: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base_pricing)
    for k, v in api_pricing.items():
        if v is not None and k not in merged:
            merged[k] = v
    return merged
