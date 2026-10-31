import sys
sys.path.insert(0, '/home/ubuntu/nse-dashboard/backend')
from app.core.credentials import credentials
from app.services.ai_advisor_service import AIAdvisorService

print(f"VM Loaded Keys Count: {len(credentials.groq_api_keys)}")
for idx, key in enumerate(credentials.groq_api_keys):
    print(f"Key #{idx+1}: {key[:12]}...{key[-4:]}")

srv = AIAdvisorService()
for i in range(3):
    res = srv.get_ai_recommendation(
        symbol='NIFTY', spot=25150.0, spot_pchange=0.45, atm_strike=25150.0,
        confluence_score=78.5, direction='BULLISH',
        chain_summary={'pcr': 1.25, 'dominant_pressure': 'CALL_BUYING'},
        indicators={'hull_state': 'BULLISH', 'alphatrend_state': 'BUY', 'adx': 28.5},
        current_option_ltp=135.0
    )
    srv._cache.clear()
    eng = res.get('ai_engine')
    act = res.get('action')
    stk = res.get('strike')
    t1 = res.get('scalp_target1')
    sl = res.get('stop_loss')
    print(f"VM Request {i+1}: Engine={eng} | Action={act} | Strike={stk} | T1={t1} | SL={sl}")
