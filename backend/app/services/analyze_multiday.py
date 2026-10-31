import json

with open('backend/app/db/multiday_backtest_audit.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

for date, day_data in data.items():
    print(f"\n==================== DATE: {date} ====================")
    trades = day_data['smart_v1']['trades']
    for t in trades:
        role = t.get('role', '')
        sym = t.get('sym', '')
        otype = t.get('otype', '')
        stk = t.get('strike', 0)
        t_in = t.get('in', '')
        t_out = t.get('out', '')
        p_in = t.get('entry', 0)
        p_out = t.get('exit', 0)
        net = t.get('net', 0)
        mfe = t.get('mfe', 0)
        mae = t.get('mae', 0)
        reason = t.get('reason', '')
        print(f"[{role:6s}] {sym:10s} {stk} {otype:2s} | In: {t_in} -> Out: {t_out} | Entry: {p_in:>7.2f} -> Exit: {p_out:>7.2f} | Net: Rs. {net:>9.2f} | MFE: Rs. {mfe:>8.2f} | MAE: Rs. {mae:>8.2f} | {reason}")
