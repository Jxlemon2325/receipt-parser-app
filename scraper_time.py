import sqlite3
import os
import time
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
import threading
import pandas as pd

driver_lock = threading.Lock()

# SQLite setup
DB_PATH = "receipts.db"

def init_price_tracking_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS item_price_tracking (
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT,
            item_name TEXT,
            price TEXT,
            searched_item TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_top_5_items():
    conn = sqlite3.connect(DB_PATH)
    top_items = pd.read_sql_query('''
        SELECT description, COUNT(*) as count
        FROM receipt_items
        WHERE description IS NOT NULL AND TRIM(description) != ''
        GROUP BY description
        ORDER BY count DESC
        LIMIT 5
    ''', conn)
    conn.close()
    return [desc for desc in top_items['description'].tolist() if desc]

def lazy_scroll(page, scroll_pause=1000, max_attempts=10):
    last_height = page.evaluate("document.body.scrollHeight")
    for _ in range(max_attempts):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(scroll_pause)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

def scrape_fairprice_selenium(search_term):
    results = []
    url = f"https://www.fairprice.com.sg/search?query={search_term}"
    with driver_lock:
        options = uc.ChromeOptions()
        options.headless = True
        driver = uc.Chrome(options=options)
        driver.get(url)

        # Scroll to load more products
        for _ in range(10):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.2)

        cards = driver.find_elements(By.CSS_SELECTOR, "[data-testid='product']")
        for card in cards:
            try:
                name_elem = card.find_element(By.CSS_SELECTOR, "[data-testid='product-name-and-metadata'] span:last-child")
                name = name_elem.text.strip() if name_elem else "N/A"

                price = "N/A"
                spans = card.find_elements(By.CSS_SELECTOR, "span")
                for span in spans:
                    text = span.text.strip()
                    if text.startswith("$"):
                        price = text
                        break

                results.append({
                    "source": "FairPrice",
                    "name": name,
                    "price": price,
                })
            except Exception:
                continue
        driver.quit()
        print(f"Found {len(results)} products on FairPrice for '{search_term}'")
        return results

def scrape_coldstorage_selenium(search_term, max_pages=3):
    with driver_lock:
        options = uc.ChromeOptions()
        options.headless = True
        driver = uc.Chrome(options=options)
        all_products = []
        for page_num in range(1, max_pages + 1):
            url = f"https://coldstorage.com.sg/en/search?keyword={search_term}&page={page_num}"
            driver.get(url)
            for _ in range(5):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            cards = driver.find_elements(By.CSS_SELECTOR, "a.ware-wrapper")
            if not cards:
                break
            for card in cards:
                try:
                    name_elem = card.find_element(By.CSS_SELECTOR, ".name")
                    price_major = card.find_element(By.CSS_SELECTOR, ".price")
                    try:
                        price_minor = card.find_element(By.CSS_SELECTOR, ".small-price")
                    except:
                        price_minor = None
                    name = name_elem.text.strip() if name_elem else "N/A"
                    price = price_major.text.strip() if price_major else "N/A"
                    if price_minor:
                        price += price_minor.text.strip()
                    all_products.append({"source": "Cold Storage", "name": name, "price": price})
                except Exception:
                    continue
        driver.quit()
        print(f"Found {len(all_products)} products on Cold Storage for '{search_term}'")
        return all_products

def scrape_shengsiong_selenium(search_term):
    url = f"https://shengsiong.com.sg/search/{search_term}"
    with driver_lock:
        options = uc.ChromeOptions()
        options.headless = False
        driver = uc.Chrome(options=options)
        driver.get(url)
        driver.minimize_window()
        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
        cards = driver.find_elements(By.CSS_SELECTOR, "a.product-preview")
        products = []
        for card in cards:
            try:
                name = card.find_element(By.CSS_SELECTOR, ".product-name").text.strip()
                price = card.find_element(By.CSS_SELECTOR, ".product-price span").text.strip()
                products.append({"source": "Sheng Siong", "name": name, "price": price})
            except Exception:
                continue
        driver.quit()
        return products

def scrape_and_store_top_prices():
    top_items = get_top_5_items()
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        for item in top_items:
            if not item:
                continue  
            for product in scrape_fairprice_selenium(item):
                conn.execute(
                    "INSERT INTO item_price_tracking (source, item_name, price, searched_item) VALUES (?, ?, ?, ?)",
                    (product['source'], product['name'], product['price'], item)
                )
            for product in scrape_coldstorage_selenium(item):
                conn.execute(
                    "INSERT INTO item_price_tracking (source, item_name, price, searched_item) VALUES (?, ?, ?, ?)",
                    (product['source'], product['name'], product['price'], item)
                )
            for product in scrape_shengsiong_selenium(item):
                conn.execute(
                    "INSERT INTO item_price_tracking (source, item_name, price, searched_item) VALUES (?, ?, ?, ?)",
                    (product['source'], product['name'], product['price'], item)
                )
        print(f"[{datetime.now()}] Scraped and stored for item: {item}")
        conn.commit()

if __name__ == "__main__":
    init_price_tracking_db()
    scrape_and_store_top_prices()
    print("Top prices scraped and stored successfully.")
