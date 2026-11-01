CYPHER 25
OPTIONAL MATCH (v:ProductVersion {changeKey: $changeKey})
RETURN v.id AS versionId
