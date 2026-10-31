import sys
import os
sys.path.insert(0, '/home/ubuntu/nse-dashboard/backend')
from app.services.radar_replay_service import radar_replay_service

res_1229 = radar_replay_service.get_replay_frame(target_date="2026-10-07", target_time="12:29")
step_1229 = res_1229["current_snapshot"]
print("=== 12:29 IST ===")
print("Time:", step_1229["time"], "Regime:", step_1229["regime"])
for idx in step_1229["indices"]:
    print(f"  {idx['symbol']}: Spot {idx['spot_price']} ({idx['spot_pchange']}%) | PCR {idx['pcr']} | Conf {idx['confluence_score']} ({idx['market_regime']}) | Dir {idx['action']} | Alpha {idx['alphatrend']} | Trend {idx['trend_direction']} | Hull {idx['hull_state']}")

res_1405 = radar_replay_service.get_replay_frame(target_date="2026-10-07", target_time="14:05")
step_1405 = res_1405["current_snapshot"]
print("\n=== 14:05 IST ===")
print("Time:", step_1405["time"], "Regime:", step_1405["regime"])
for idx in step_1405["indices"]:
    print(f"  {idx['symbol']}: Spot {idx['spot_price']} ({idx['spot_pchange']}%) | PCR {idx['pcr']} | Conf {idx['confluence_score']} ({idx['market_regime']}) | Dir {idx['action']} | Alpha {idx['alphatrend']} | Trend {idx['trend_direction']} | Hull {idx['hull_state']}")
