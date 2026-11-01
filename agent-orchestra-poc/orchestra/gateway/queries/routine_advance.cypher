CYPHER 25
MATCH (r:Routine {id: $id})
SET r.nextRunAt = CASE WHEN $nextRunAt IS NULL THEN r.nextRunAt ELSE datetime($nextRunAt) END,
    r.lastFiredAt = CASE WHEN $fired IS NULL THEN r.lastFiredAt ELSE datetime($fired) END,
    r.lastSkippedAt = CASE WHEN $skipped IS NULL THEN r.lastSkippedAt ELSE datetime($skipped) END,
    r.lastError = CASE WHEN $error IS NULL THEN r.lastError ELSE $error END,
    r.firedAt = CASE WHEN $disable AND $fired IS NOT NULL THEN datetime($fired) ELSE r.firedAt END,
    r.enabled = CASE WHEN $disable THEN false ELSE r.enabled END
RETURN r.id AS id, r.enabled AS enabled
