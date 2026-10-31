import json
import os
import sys

# Ensure backend path is in sys.path
sys.path.insert(0, "/home/ubuntu/nse-dashboard/backend")

from app.services.fyers_fetcher import fyers_service, HAS_FYERS
from app.providers.data_source_manager import data_source_manager
from app.services.market_hours import get_market_session_info, is_market_open

print("--- 1. MARKET SESSION CHECK ---")
session_info = get_market_session_info()
print("Session Info:", session_info)
print("Is Market Open:", is_market_open())

print("\n--- 2. FYERS PROVIDER DIAGNOSTIC ---")
print("HAS_FYERS library installed:", HAS_FYERS)
print("Client ID Present:", bool(fyers_service.client_id))
print("Access Token Present:", bool(fyers_service.access_token))
print("Fyers Client Initialized:", fyers_service.fyers is not None)
print("Fyers Is Configured:", fyers_service.is_configured())

valid, msg = fyers_service.validate_connection()
print("Fyers Validate Connection Result:", valid, "| Message:", msg)
print("Fyers Last Error:", fyers_service.last_error)

print("\n--- 3. DATASOURCE MANAGER DIAGNOSTIC ---")
health_dict = data_source_manager.get_system_health()
print("Active Provider:", health_dict.get("active_provider") if isinstance(health_dict, dict) else getattr(health_dict, "active_provider", "unknown"))

providers = health_dict.get("providers") if isinstance(health_dict, dict) else getattr(health_dict, "providers", {})
for name, p_health in providers.items():
    print(f"Provider: {name}")
    if isinstance(p_health, dict):
        print(f"  Healthy: {p_health.get('is_healthy')}")
        print(f"  Consecutive Failures: {p_health.get('consecutive_failures')}")
        print(f"  Total Requests: {p_health.get('total_requests')}")
        print(f"  Successful Requests: {p_health.get('successful_requests')}")
        print(f"  Last Error: {p_health.get('last_error')}")
    else:
        print(f"  Healthy: {getattr(p_health, 'is_healthy', None)}")
        print(f"  Consecutive Failures: {getattr(p_health, 'consecutive_failures', None)}")
        print(f"  Total Requests: {getattr(p_health, 'total_requests', None)}")
        print(f"  Successful Requests: {getattr(p_health, 'successful_requests', None)}")
        print(f"  Last Error: {getattr(p_health, 'last_error', None)}")

print("\n--- 4. TEST SNAPSHOT FETCH FOR EACH PROVIDER ---")
import asyncio

async def test_providers():
    for p in data_source_manager.providers:
        name = p.provider_name()
        avail = p.is_available()
        print(f"Testing provider '{name}' (is_available={avail})...")
        try:
            snap = await p.get_market_snapshot("NIFTY")
            if snap:
                print(f"  -> SUCCESS! Got snapshot for NIFTY spot={snap.spot.spot_price}")
            else:
                print(f"  -> Returned None (Unavailable or fetch failed)")
        except Exception as e:
            print(f"  -> Exception: {e}")

asyncio.run(test_providers())
