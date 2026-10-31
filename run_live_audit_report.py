"""
V3.2 Live Market Validation Report Generator (Phase 18).
Generates the official daily VCC LIVE VALIDATION REPORT matching all 11 mandatory sections.
Enforces sample governance, terminology policies, and distinction between Observed Fact, Model Interpretation, and Insufficient Data.
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.services.live_signal_audit_service import live_signal_audit_service
from app.db.database import init_db

def generate_report(symbol: str = "NIFTY", target_date: str = None):
    init_db()
    live_signal_audit_service.evaluate_pending_signal_outcomes(symbol)
    rep = live_signal_audit_service.get_audit_summary_report(symbol=symbol, target_date=target_date)

    date_str = rep.get("date", datetime.now().strftime("%Y-%m-%d"))
    symbol_str = rep.get("symbol", "NIFTY")
    sample_quality = rep.get("sample_quality", "INSUFFICIENT SAMPLE")

    lines = []
    lines.append(f"# VCC LIVE VALIDATION REPORT — {symbol_str} ({date_str})")
    lines.append(f"**Sample Governance Classification**: `{sample_quality}`\n")
    lines.append("> [!IMPORTANT]")
    lines.append("> **STATISTICAL GOVERNANCE & TERMINOLOGY DISCLOSURE**")
    lines.append("> 1. **MODEL CONFIDENCE** is an evidence-weighted score (0–100%), NOT a win probability.")
    lines.append(f"> 2. **Directional Move Threshold**: Requires minimum spot movement of **{rep.get('min_directional_move_pts', 15.0)} pts (~0.06%)** to classify outcomes as CORRECT vs NEUTRAL.")
    lines.append(f"> 3. **Observational Governance**: No model optimization or recalibration during data collection.\n")

    # 1. SIGNAL DISTRIBUTION
    lines.append("## 1. SIGNAL DISTRIBUTION")
    lines.append(f"- **Total Signals Logged**: {rep.get('total_signals', 0)} *(OBSERVED FACT)*")
    lines.append(f"- **Valid Snapshots**: {rep.get('valid_signals', 0)}")
    lines.append(f"- **Bullish Signals**: {rep.get('bullish_signals', 0)}")
    lines.append(f"- **Bearish Signals**: {rep.get('bearish_signals', 0)}")
    lines.append(f"- **Degraded/Invalid Snapshots**: {rep.get('invalid_data_signals', 0)} invalid / {rep.get('degraded_data_signals', 0)} degraded\n")

    # 2. DIRECTIONAL ACCURACY
    outcomes = rep.get("outcomes", {})
    lines.append("## 2. DIRECTIONAL ACCURACY")
    lines.append(f"- **Evaluated Signals**: {outcomes.get('evaluated_signals', 0)}")
    lines.append(f"- **5-Min Accuracy**: {outcomes.get('accuracy_5m_pct', 0.0)}%")
    lines.append(f"- **15-Min Accuracy**: {outcomes.get('accuracy_15m_pct', 0.0)}%")
    lines.append(f"- **30-Min Accuracy**: {outcomes.get('accuracy_30m_pct', 0.0)}%")
    lines.append(f"- **Correct Signals**: {outcomes.get('correct_signals', 0)} | **False Signals**: {outcomes.get('false_signals', 0)}\n")

    # 3. CONFLUENCE CALIBRATION
    lines.append("## 3. CONFLUENCE CALIBRATION")
    lines.append("| Confluence Bucket | N | 5M Acc | 15M Acc | 30M Acc | Avg Return | MFE / MAE | Governance |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for b_name, b_data in rep.get("confluence_calibration", {}).items():
        lines.append(f"| {b_name} | {b_data['N']} | {b_data['accuracy_5m_pct']}% | {b_data['accuracy_15m_pct']}% | {b_data['accuracy_30m_pct']}% | {b_data['avg_return_pct']}% | +{b_data['avg_mfe_pct']}% / -{b_data['avg_mae_pct']}% | `{b_data['sample_quality']}` |")
    lines.append("")

    # 4. CONFIDENCE CALIBRATION
    lines.append("## 4. CONFIDENCE CALIBRATION")
    lines.append("| Confidence Tier | N | 15M Accuracy | Governance |")
    lines.append("|---|---|---|---|")
    for c_name, c_data in rep.get("confidence_calibration", {}).items():
        lines.append(f"| {c_name} | {c_data['N']} | {c_data['accuracy_15m_pct']}% | `{c_data['sample_quality']}` |")
    lines.append("")

    # 5. TIME-OF-DAY PERFORMANCE
    lines.append("## 5. TIME-OF-DAY PERFORMANCE")
    lines.append("| Session Slot | Signals (Bull/Bear) | 5M Acc | 15M Acc | 30M Acc | Avg Confluence | Governance |")
    lines.append("|---|---|---|---|---|---|---|")
    for s_slot, s_data in rep.get("time_of_day_performance", {}).items():
        lines.append(f"| {s_slot} | {s_data['signal_count']} ({s_data['bullish_count']}B / {s_data['bearish_count']}B) | {s_data['accuracy_5m_pct']}% | {s_data['accuracy_15m_pct']}% | {s_data['accuracy_30m_pct']}% | {s_data['avg_confluence']} | `{s_data['sample_quality']}` |")
    lines.append("")

    # 6. MARKET-REGIME PERFORMANCE
    lines.append("## 6. MARKET-REGIME PERFORMANCE")
    lines.append("| Market Regime | Signal Count | 15M Accuracy | Governance |")
    lines.append("|---|---|---|---|")
    for r_name, r_data in rep.get("market_regime_performance", {}).items():
        lines.append(f"| {r_name} | {r_data['signal_count']} | {r_data['accuracy_15m_pct']}% | `{r_data['sample_quality']}` |")
    lines.append("")

    # 7. FALSE SIGNAL ANALYSIS
    lines.append("## 7. FALSE SIGNAL ANALYSIS")
    false_map = rep.get("false_signal_analysis", {})
    if false_map:
        for k, v in false_map.items():
            lines.append(f"- **{k}**: {v} occurrence(s)")
    else:
        lines.append("- No false signal categories recorded.")
    lines.append("")

    # 8. MFE / MAE
    excursions = rep.get("excursions", {})
    lines.append("## 8. MFE / MAE (MAX FAVOURABLE / ADVERSE EXCURSION)")
    lines.append(f"- **Average MFE (30m)**: +{excursions.get('avg_mfe_pct', 0.0)}% *(OBSERVED FACT)*")
    lines.append(f"- **Average MAE (30m)**: -{excursions.get('avg_mae_pct', 0.0)}% *(OBSERVED FACT)*\n")

    # 9. DATA QUALITY
    dq = rep.get("data_quality_report", {})
    lines.append("## 9. DATA QUALITY")
    lines.append(f"- **Data Quality Good**: {dq.get('data_quality_good', 0)}")
    lines.append(f"- **Data Quality Degraded**: {dq.get('data_quality_degraded', 0)}")
    lines.append(f"- **Data Quality Invalid**: {dq.get('data_quality_invalid', 0)} *(Excluded from statistics)*\n")

    # 10. SAMPLE SIZE
    lines.append("## 10. SAMPLE SIZE GOVERNANCE")
    lines.append(f"- **Current Total Sample ($N$)**: {rep.get('total_signals', 0)}")
    lines.append(f"- **Governance Status**: `{sample_quality}`")
    lines.append("- **Policy**: No statistical conclusions or threshold recalibrations allowed until $N \\ge 100$.\n")

    # 11. LIMITATIONS & DISCLOSURE
    lines.append("## 11. LIMITATIONS & STATISTICAL GOVERNANCE")
    lines.append("- **OBSERVED FACT**: All numbers represent raw empirical observation recorded from live market feeds.")
    lines.append("- **MODEL INTERPRETATION**: Signal labels reflect rule-based evidence weighting, not future market direction guarantee.")
    lines.append("- **INSUFFICIENT DATA**: No claim of predictive edge or profitability is made.")
    lines.append("- **GOVERNANCE RULE**: Thresholds remain frozen until sample size satisfies statistical confidence criteria.")

    report_content = "\n".join(lines)
    print(report_content)

    # Save artifact
    artifact_path = os.path.join(os.path.dirname(__file__), "vcc_live_validation_report.md")
    with open(artifact_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nReport written to {artifact_path}")

if __name__ == "__main__":
    generate_report()
