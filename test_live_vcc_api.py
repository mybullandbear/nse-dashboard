import urllib.request
import json

symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

for sym in symbols:
    url = f"http://localhost:8000/api/dashboard/{sym}"
    try:
        req = urllib.request.urlopen(url)
        data = json.loads(req.read().decode('utf-8'))
        intel = data.get('vcc_intelligence', {})
        print(f"=== {sym} DATA API STATUS ===")
        print(f"Symbol: {intel.get('symbol')}")
        print(f"Session State: {intel.get('market_session_state')}")
        print(f"Operational State: {intel.get('signal_meta', {}).get('operational_state')}")
        print(f"Execution Status: {intel.get('signal_meta', {}).get('execution_status')}")
        print(f"Flow Directional Label: {intel.get('flow_engine', {}).get('directional_flow_label')}")
        print(f"Net Flow Lakhs: {intel.get('flow_engine', {}).get('net_flow_lakhs')}")
        print(f"Total Activity Lakhs: {intel.get('flow_engine', {}).get('total_activity_lakhs')}")
        print(f"Evidence Ratio: {intel.get('final_confluence', {}).get('evidence_ratio')}")
        print(f"Sample Classification: {intel.get('signal_meta', {}).get('historical_reliability', {}).get('sample_classification')}")
        matrix = intel.get('strike_matrix', [])
        print(f"Strike Matrix Length: {len(matrix)}")
        if matrix:
            atm_row = next((m for m in matrix if m.get('is_atm')), matrix[len(matrix)//2])
            print(f"ATM Strike: {atm_row.get('strike')}")
            print(f"ATM PE Action: {atm_row.get('pe_classification')}")
            print(f"ATM CE Action: {atm_row.get('ce_classification')}")
            print(f"ATM Battle Status: {atm_row.get('battle_status')}")
        print()
    except Exception as e:
        print(f"Error fetching {sym}: {e}")
