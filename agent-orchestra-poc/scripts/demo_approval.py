"""Create a pending committee approval, without any LLM (for the demo and the UI tests).
Run inside the cdc container: docker compose --profile app exec -T cdc python scripts/demo_approval.py"""
import os
import uuid

import httpx

from orchestra.gateway.auth import make_token

M = os.environ["ORCHESTRA_MASTER_KEY"]
GW = os.environ.get("GATEWAY_URL", "http://gateway:8000")
h = lambda kind, who: {"Authorization": "Bearer " + make_token(M, kind, who)}

mid = f"demo-trigger-{uuid.uuid4().hex[:8]}"
r = httpx.post(f"{GW}/internal/deliver", headers=h("sys", "cdc"), json={
    "id": mid, "from": "routine:demo", "actingAgent": "coordinateur", "inbox": "inbox:coordinateur", "body": "Synthesis ready for the decision."})
r.raise_for_status()
sid = httpx.post(f"{GW}/sessions", headers=h("svc", "coordinateur"), json={"messageId": mid}).raise_for_status().json()["id"]
ap = httpx.post(f"{GW}/approvals", headers=h("svc", "coordinateur"), json={
    "sessionId": sid, "tool": "launch_modification", "idempotencyKey": f"demo-{mid}", "electorate": "inbox:comite",
    "args": {"part_id": "PRT-0045", "replacement_id": "PRT-0102", "description": "Replace relay PRT-0045 with PRT-0102 (estimated delay: 11 days)."}})
ap.raise_for_status()
httpx.post(f"{GW}/sessions/{sid}/close", headers=h("svc", "coordinateur"), json={"status": "input-required"}).raise_for_status()
print(ap.json()["id"])
