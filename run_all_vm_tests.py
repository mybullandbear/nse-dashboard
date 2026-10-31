import os
import subprocess
import sys

test_files = [
    "tests/test_domain_contracts.py",
    "tests/test_data_source_manager.py",
    "tests/test_analytics_pipeline.py",
    "tests/test_signal_decision_engine.py",
    "tests/test_audit_governance_anti_lookahead.py",
    "tests/test_persistence_repositories.py",
    "tests/test_vcc_api_presentation.py",
    "tests/test_replay_research_engine.py",
    "test_v32_20_conditions_audit.py"
]

passed_count = 0
failed_count = 0

print("=====================================================")
print("  EXECUTING DEPLOYED RELEASE CANDIDATE TEST MATRIX   ")
print("=====================================================")

for tf in test_files:
    if not os.path.exists(tf):
        print(f"[FAIL] {tf} NOT FOUND")
        failed_count += 1
        continue
    res = subprocess.run([sys.executable, tf], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"[PASS] {tf}")
        passed_count += 1
    else:
        print(f"[FAIL] {tf}")
        print("STDOUT:", res.stdout[-300:])
        print("STDERR:", res.stderr[-300:])
        failed_count += 1

print("=====================================================")
print(f"RESULTS: {passed_count}/{len(test_files)} TEST SUITES PASSED")
print("=====================================================")
