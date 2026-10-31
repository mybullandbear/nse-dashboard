import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1920,1080')
options.add_argument('--disable-gpu')

artifact_dir = r"C:\Users\resea\.gemini\antigravity-ide\brain\22b1ac81-0931-4c3a-9bf8-1c2a910bbcf8"
os.makedirs(artifact_dir, exist_ok=True)

driver = webdriver.Chrome(options=options)
try:
    print("[1/6] Navigating to http://127.0.0.1:8000/...")
    driver.get("http://127.0.0.1:8000/")
    time.sleep(3)

    logs = driver.get_log("browser")
    errs = [l for l in logs if l["level"] == "SEVERE"]
    print(f"Browser severe errors: {len(errs)}")
    for e in errs:
        print(f"  ERR: {e['message']}")

    # 1. Default dual view: NIFTY & BANKNIFTY
    p1 = os.path.join(artifact_dir, "dual_view_nifty_banknifty.png")
    driver.save_screenshot(p1)
    print(f"[2/6] Default dual view saved: {p1}")

    # 2. Toggle to FINNIFTY & MIDCAP
    pair2_btn = driver.find_element(By.CSS_SELECTOR, "[data-pair='FINNIFTY_MIDCPNIFTY']")
    pair2_btn.click()
    time.sleep(2.5)
    p2 = os.path.join(artifact_dir, "dual_view_finnifty_midcap.png")
    driver.save_screenshot(p2)
    print(f"[3/6] Secondary dual view (FINNIFTY & MIDCAP) saved: {p2}")

    # 3. Toggle back to NIFTY & BANKNIFTY
    pair1_btn = driver.find_element(By.CSS_SELECTOR, "[data-pair='NIFTY_BANKNIFTY']")
    pair1_btn.click()
    time.sleep(1.5)

    # 4. View Signals Radar dual view
    sig_tab = driver.find_element(By.CSS_SELECTOR, "[data-tab='signals']")
    sig_tab.click()
    time.sleep(2)
    p3 = os.path.join(artifact_dir, "dual_view_signals.png")
    driver.save_screenshot(p3)
    print(f"[4/6] Dual Signals view saved: {p3}")

    # 5. View Smart Money dual view
    sm_tab = driver.find_element(By.CSS_SELECTOR, "[data-tab='smart-money']")
    sm_tab.click()
    time.sleep(2)
    p4 = os.path.join(artifact_dir, "dual_view_smart_money.png")
    driver.save_screenshot(p4)
    print(f"[5/6] Dual Smart Money view saved: {p4}")

    # 6. View Option Chain view
    chain_tab = driver.find_element(By.CSS_SELECTOR, "[data-tab='chain']")
    chain_tab.click()
    time.sleep(2)
    p5 = os.path.join(artifact_dir, "dual_view_option_chain.png")
    driver.save_screenshot(p5)
    print(f"[6/6] Option Chain view saved: {p5}")

    print("\n[SUCCESS] All simultaneous dual-view screenshots captured successfully.")

except Exception as ex:
    print(f"[ERROR] Test failed: {ex}")
    raise
finally:
    driver.quit()
