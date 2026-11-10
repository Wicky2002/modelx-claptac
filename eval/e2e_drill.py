"""Run the Ditwah drill end to end through the API, as an operator would.

    python eval/e2e_drill.py http://localhost:8000

Checks: the replay finishes, an incident opens, the public alert waits for a person, and after approval
the alert is issued with Sinhala and Tamil text. Exits 1 if any check fails. CI runs it against the
Docker image.
"""

import json
import sys
import time
import urllib.request

BASE = sys.argv[1].rstrip("/")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "null")


ok = True


def check(cond, label):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    ok &= bool(cond)


check(call("GET", "/health"), "health")
keys = [s["key"] for s in call("GET", "/play/scenarios")]
check("ratnapura_ditwah_2025" in keys, f"scenario listed ({len(keys)} scenarios)")
started = call("POST", "/play/scenarios/start", {"scenario": "ratnapura_ditwah_2025", "speed": 60})
print("  started", started.get("total"), "readings at", started.get("speed"))
deadline = time.time() + 600
while time.time() < deadline:
    st = call("GET", "/play/scenarios/status")
    if st["state"] not in ("running", "starting"):
        break
    time.sleep(3)
print("  replay", st["state"], st.get("sent"), "/", st.get("total"))
check(st.get("sent") == st.get("total"), "every reading replayed")
time.sleep(5)
incidents = call("GET", "/incidents")
check(len(incidents) >= 1, f"incident opened ({len(incidents)})")
inc = incidents[0]
print("  incident:", {k: inc.get(k) for k in ("id", "hazard", "status", "severity") if k in inc})
approvals = call("GET", "/approvals")
kinds = sorted({a["action"]["action_type"] for a in approvals})
check(len(approvals) >= 1, f"approvals waiting ({len(approvals)}): {kinds}")
alert_req = [a for a in approvals if "alert" in a["action"]["action_type"]]
check(alert_req, "public alert waits for a person")
for a in alert_req[:1]:
    res = call("POST", f"/approvals/{a['id']}/approve", {"reviewer": "E2E Check"})
    print("  approved:", res.get("status"))
time.sleep(5)
alerts = call("GET", "/alerts")
check(len(alerts) >= 1, f"alert issued ({len(alerts)})")
if alerts:
    detail = call("GET", f"/alerts/{alerts[0]['id']}") if "id" in alerts[0] else alerts[0]
    text = json.dumps(detail, ensure_ascii=False)
    check(any("\u0d80" <= ch <= "\u0dff" for ch in text), "Sinhala text present")
    check(any("\u0b80" <= ch <= "\u0bff" for ch in text), "Tamil text present")
missions = call("GET", "/missions")
print("  missions:", len(missions))
print("ALL PASS" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
