from playwright.sync_api import sync_playwright
import time
import json
import re
from datetime import datetime
import os

def extract_listing_id(url):
    if not url:
        return None
    m = re.search(r"-(\d+)/", url)
    return m.group(1) if m else None


def to_int(x):
    if not x:
        return None
    digits = re.sub(r"[^\d]", "", x)
    return int(digits) if digits else None


def clean_date(s):
    if not s:
        return None
    s = s.replace("Posted ", "").strip()
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except:
        return None


def clean_reg_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except:
        return None


def clean_owners(s):
    if not s:
        return None
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None

def should_run_headless():
    return os.getenv("GITHUB_ACTIONS", "").lower() == "true"

BASE_URL = "https://www.sgcarmart.com/used_cars/listing.php"

MAX_PAGES = 2
PAGE_SIZE = 20


def scrape():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=should_run_headless())
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-SG",
            timezone_id="Asia/Singapore"
        )
        page = context.new_page()
        print(f"[INFO] Running headless={should_run_headless()}")

        for page_num in range(MAX_PAGES):
            offset = page_num * PAGE_SIZE
            url = f"{BASE_URL}?BRSR={offset}"

            for attempt in range(3):
                try:
                    page.goto(url, timeout=60000)
                    break
                except:
                    print(f"[RETRY] {url}")
                    time.sleep(2)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1000)
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1000)

            print(f"[INFO] Loading {url}")


            try:
                page.wait_for_selector("a[href*='used-cars/info']", timeout=20000)
            except:
                print("[WARN] Main container not found, retrying...")
                page.wait_for_timeout(8000)

            containers = page.query_selector_all("div[class*='listing_listing_container'] > div")

            print(f"[DEBUG] Found {len(containers)} containers")

            for item in containers:
                try:
                    box = item.query_selector("div[class*='styles_listing_box']")
                    if not box:
                        continue

                    text = box.inner_text().strip()

                    # 🔗 Extract link
                    link_el = item.query_selector("a[href*='used-cars/info']")
                    href = link_el.get_attribute("href") if link_el else None

                    if href and href.startswith("/"):
                        href = "https://www.sgcarmart.com" + href

                    # 🖼️ Extract thumbnail image
                    img_el = item.query_selector("img[src*='cars_used']")
                    img_src = img_el.get_attribute("src") if img_el else None

                    # ✅ Append structured data
                    lines = [l.strip() for l in text.split("\n") if l.strip()]

                    # Handle cases like "PREMIUM AD" or "DIRECT OWNER"
                    title = None
                    ad_type = "STANDARD"

                    if lines:
                        if lines[0] in ["PREMIUM AD", "DIRECT OWNER"]:
                            ad_type = lines[0]
                            title = lines[1] if len(lines) > 1 else None
                        else:
                            title = lines[0]

                    # Extract pricing fields
                    price = next((l for l in lines if l.startswith("$")), None)
                    monthly = next((l for l in lines if "/mth" in l), None)
                    depreciation = next((l for l in lines if "/yr" in l), None)

                    reg_date = next(
                        (l for l in lines if re.match(r"\d{2}-[A-Za-z]{3}-\d{4}", l)),
                        None
                    )

                    if reg_date:
                        reg_date = reg_date.split(" ")[0]

                    coe = next((l for l in lines if "COE left" in l), None)

                    mileage = next((l for l in lines if "km" in l), None)
                    engine = next((l for l in lines if "cc" in l), None)
                    owners = next((l for l in lines if re.search(r"\d+\s*Owner", l)), None)

                    posted = next((l for l in lines if "Posted" in l), None)

                    # Extract optional fields
                    fuel_type = next((l.replace("Fuel Type:", "").strip() for l in lines if "Fuel Type" in l), None)

                    # Dealer name (usually before '|')
                    dealer_name = None
                    for i, l in enumerate(lines):
                        if l == "|" and i > 0:
                            dealer_name = lines[i-1]

                    # Simple tag extraction
                    tags = []
                    text_lower = text.lower()
                    if "accident free" in text_lower:
                        tags.append("accident_free")
                    if "1 owner" in text_lower or "1 ownership" in text_lower:
                        tags.append("single_owner")
                    if "low mileage" in text_lower:
                        tags.append("low_mileage")
                    if "well maintained" in text_lower:
                        tags.append("well_maintained")
                    if "loan" in text_lower:
                        tags.append("financing_available")

                    listing_id = extract_listing_id(href)

                    results.append({
                        "listing_id": listing_id,
                        "title": title,
                        "ad_type": ad_type,
                        "is_premium": ad_type == "PREMIUM AD",

                        "price": to_int(price),
                        "monthly_installment": to_int(monthly),
                        "depreciation": to_int(depreciation),

                        "registration_date": clean_reg_date(reg_date),
                        "coe_remaining": coe,
                        "mileage": to_int(mileage),
                        "engine_cc": to_int(engine),
                        "owners": clean_owners(owners),

                        "posted_date": clean_date(posted),

                        "fuel_type": fuel_type,
                        "dealer_name": dealer_name,
                        "tags": tags,

                        "link": href,
                        "image": img_src,

                        "scraped_at": datetime.utcnow().isoformat()
                    })

                except Exception as e:
                    print("[ERROR]", e)
                    continue

            time.sleep(0.3)

        browser.close()

    return results


def save(data):
    with open("sgcarmart.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[INFO] Saved {len(data)} rows to JSON")


if __name__ == "__main__":
    data = scrape()
    save(data)
