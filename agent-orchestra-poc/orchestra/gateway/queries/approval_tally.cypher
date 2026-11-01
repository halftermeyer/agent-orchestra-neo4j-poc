CYPHER 25
MATCH (ap:Approval {id: $approvalId})-[:FOR]->(tc:ToolCall)
CALL (ap) {
  MATCH (:Agent)-[v:VOTED]->(ap)
  RETURN count(CASE WHEN v.decision = 'approve' THEN 1 END) AS yes, count(CASE WHEN v.decision = 'reject' THEN 1 END) AS no
}
WITH ap, tc, yes, no, ap.status AS prev,
     CASE WHEN ap.status <> 'pending' THEN ap.status
          WHEN yes >= ap.quorum THEN 'approved'
          WHEN no > ap.size - ap.quorum THEN 'rejected'
          ELSE 'pending' END AS next
SET ap.status = next,
    ap.decidedAt = CASE WHEN prev = 'pending' AND next <> 'pending' THEN datetime() ELSE ap.decidedAt END
WITH ap, tc, yes, no, prev, next
SET tc.status = CASE WHEN prev = 'pending' AND next = 'approved' THEN 'working'
                     WHEN prev = 'pending' AND next = 'rejected' THEN 'canceled' ELSE tc.status END,
    tc.workingAt = CASE WHEN prev = 'pending' AND next = 'approved' THEN datetime() ELSE tc.workingAt END,
    tc.endedAt = CASE WHEN prev = 'pending' AND next = 'rejected' THEN datetime() ELSE tc.endedAt END
RETURN ap.status AS status, yes, no, tc.status AS toolCallStatus
