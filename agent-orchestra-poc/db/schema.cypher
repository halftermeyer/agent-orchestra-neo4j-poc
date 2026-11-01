// Schéma de la base d'orchestration. Idempotent (IF NOT EXISTS). Appliqué par db/init/init.sh.
// Les entités que le consommateur CDC doit identifier à partir des seuls événements sont des NODE KEY :
// le CDC ne publie `keys` que pour les clés de nœud (spike phase 3). Plus strict que l'unicité de la spec.
CYPHER 25
DROP CONSTRAINT agent_id IF EXISTS;
DROP CONSTRAINT message_id IF EXISTS;
DROP CONSTRAINT session_trigger IF EXISTS;
DROP CONSTRAINT inbox_id IF EXISTS;
DROP CONSTRAINT memory_id IF EXISTS;
DROP CONSTRAINT chain_id IF EXISTS;
DROP CONSTRAINT tool_name IF EXISTS;
DROP CONSTRAINT toolcall_idem IF EXISTS;
DROP CONSTRAINT approval_id IF EXISTS;
CREATE CONSTRAINT agent_key IF NOT EXISTS FOR (n:Agent) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT message_key IF NOT EXISTS FOR (n:Message) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT session_key IF NOT EXISTS FOR (n:Session) REQUIRE n.triggerMsgId IS NODE KEY;
CREATE CONSTRAINT inbox_key IF NOT EXISTS FOR (n:Inbox) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT inboxday_key IF NOT EXISTS FOR (n:InboxDay) REQUIRE (n.inboxId, n.date) IS NODE KEY;
CREATE CONSTRAINT workday_key IF NOT EXISTS FOR (n:WorkDay) REQUIRE (n.workspaceId, n.date) IS NODE KEY;
CREATE CONSTRAINT workspace_id IF NOT EXISTS FOR (n:Workspace) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT memory_key IF NOT EXISTS FOR (n:Memory) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (n:Fact) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT version_id IF NOT EXISTS FOR (n:AgentVersion) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT mandate_id IF NOT EXISTS FOR (n:Mandate) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT commitment_id IF NOT EXISTS FOR (n:Commitment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT routine_id IF NOT EXISTS FOR (n:Routine) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT chain_key IF NOT EXISTS FOR (n:Chain) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT tool_key IF NOT EXISTS FOR (n:Tool) REQUIRE n.name IS NODE KEY;
CREATE CONSTRAINT toolcall_key IF NOT EXISTS FOR (n:ToolCall) REQUIRE n.idempotencyKey IS NODE KEY;
CREATE CONSTRAINT approval_key IF NOT EXISTS FOR (n:Approval) REQUIRE n.id IS NODE KEY;
CREATE CONSTRAINT kg_id IF NOT EXISTS FOR (n:KnowledgeGraph) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT entityref_key IF NOT EXISTS FOR (n:EntityRef) REQUIRE (n.db, n.key) IS NODE KEY;
// Un vote par personne et par validation
CREATE CONSTRAINT vote_once IF NOT EXISTS FOR ()-[r:VOTED]-() REQUIRE (r.approvalId, r.personId) IS UNIQUE;

CREATE INDEX message_chain IF NOT EXISTS FOR (n:Message) ON (n.chainId);
CREATE INDEX message_conv IF NOT EXISTS FOR (n:Message) ON (n.conversationId);
CREATE INDEX message_created IF NOT EXISTS FOR (n:Message) ON (n.createdAt);
CREATE INDEX fact_memory IF NOT EXISTS FOR (n:Fact) ON (n.memoryId);
CREATE INDEX received_status IF NOT EXISTS FOR ()-[r:RECEIVED]-() ON (r.status);

// Dimension 768 : gemini-embedding-001 avec outputDimensionality=768 (à confirmer en phase 2).
// WITH [memoryId] : propriété de filtre pour SEARCH ... WHERE (spike 4).
CREATE VECTOR INDEX fact_embedding IF NOT EXISTS FOR (f:Fact) ON (f.embedding) WITH [f.memoryId]
  OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}};
