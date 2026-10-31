import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=390,844') # iPhone 14 Pro viewport
options.add_argument('--disable-gpu')

artifact_dir = r"C:\Users\resea\.gemini\antigravity-ide\brain\22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8"
os.makedirs(artifact_dir, exist_ok=True)

driver = webdriver.Chrome(options=options)
try:
    print("[1/5] Navigating to http://127.0.0.1:8000 on Mobile Viewport (390x844)...")
    driver.get("http://127.0.0.1:8000/")
    time.sleep(3)

    # Check console errors
    logs = driver.get_log("browser")
    errs = [l for l in logs if l["level"] == "SEVERE"]
    print(f"Browser severe errors: {len(errs)}")
    for e in errs:
        print(f"  ERR: {e['message']}")

    # 1. Mobile top view: Header, Pair Buttons, Ticker 2x2, Tabs, NIFTY 50
    p1 = os.path.join(artifact_dir, "mobile_view_top.png")
    driver.save_screenshot(p1)
    print(f"[2/5] Saved mobile top view: {p1}")

    # 2. Scroll slightly to view NIFTY timeline & strike bars
    driver.execute_script("window.scrollBy(0, 400);")
    time.sleep(1)
    p2 = os.path.join(artifact_dir, "mobile_view_nifty_timeline.png")
    driver.save_screenshot(p2)
    print(f"[3/5] Saved mobile timeline view: {p2}")

    # 3. Scroll further to view BANKNIFTY
    driver.execute_script("window.scrollBy(0, 700);")
    time.sleep(1)
    p3 = os.path.join(artifact_dir, "mobile_view_banknifty.png")
    driver.save_screenshot(p3)
    print(f"[4/5] Saved mobile banknifty view: {p3}")

    # 4. Mobile Option Chain Matrix
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(0.5)
    chain_btn = driver.find_element(By.CSS_SELECTOR, "[data-tab='chain']")
    chain_btn.click()
    time.sleep(2)
    p4 = os.path.join(artifact_dir, "mobile_view_option_chain.png")
    driver.save_screenshot(p4)
    print(f"[5/5] Saved mobile option chain view: {p4}")

    print("\n[SUCCESS] All mobile view verification screenshots saved successfully.")

except Exception as ex:
    print(f"[ERROR] Mobile test failed: {ex}")
    raise
finally:
    driver.quit()
