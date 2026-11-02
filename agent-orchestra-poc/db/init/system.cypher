// Idempotent: databases, composite, aliases, users, roles, CDC. Run against the `system`.
CREATE DATABASE orchestra IF NOT EXISTS WAIT;
CREATE DATABASE kgproduit IF NOT EXISTS WAIT;
CREATE DATABASE kgprojet IF NOT EXISTS WAIT;
CREATE COMPOSITE DATABASE fed IF NOT EXISTS;
CREATE ALIAS fed.orchestra IF NOT EXISTS FOR DATABASE orchestra;
CREATE ALIAS fed.kgproduit IF NOT EXISTS FOR DATABASE kgproduit;
CREATE ALIAS fed.kgprojet IF NOT EXISTS FOR DATABASE kgprojet;

ALTER DATABASE orchestra SET OPTION txLogEnrichment 'FULL';
ALTER DATABASE kgproduit SET OPTION txLogEnrichment 'FULL';
ALTER DATABASE kgprojet SET OPTION txLogEnrichment 'FULL';

// Utilisateurs distincts : administration, passerelle, CDC
CREATE USER admin IF NOT EXISTS SET PASSWORD $adminPw CHANGE NOT REQUIRED;
GRANT ROLE admin TO admin;

CREATE ROLE gateway_rw IF NOT EXISTS;
CREATE USER gateway IF NOT EXISTS SET PASSWORD $gatewayPw CHANGE NOT REQUIRED;
GRANT ROLE gateway_rw TO gateway;
GRANT ACCESS ON DATABASE orchestra TO gateway_rw;
GRANT MATCH {*} ON GRAPH orchestra TO gateway_rw;
GRANT WRITE ON GRAPH orchestra TO gateway_rw;
GRANT NAME MANAGEMENT ON DATABASE orchestra TO gateway_rw;
GRANT ACCESS ON DATABASE kgproduit TO gateway_rw;
GRANT MATCH {*} ON GRAPH kgproduit TO gateway_rw;
GRANT ACCESS ON DATABASE kgprojet TO gateway_rw;
GRANT MATCH {*} ON GRAPH kgprojet TO gateway_rw;
GRANT ACCESS ON DATABASE fed TO gateway_rw;
GRANT EXECUTE PROCEDURE apoc.util.* ON DBMS TO gateway_rw;
GRANT EXECUTE PROCEDURE gds.* ON DBMS TO gateway_rw;

// Minimal CDC privileges (spike 2) : ACCESS + EXECUTE BOOSTED PROCEDURE db.cdc.*
CREATE ROLE cdc_reader IF NOT EXISTS;
CREATE USER cdc IF NOT EXISTS SET PASSWORD $cdcPw CHANGE NOT REQUIRED;
GRANT ROLE cdc_reader TO cdc;
GRANT ACCESS ON DATABASE orchestra TO cdc_reader;
GRANT ACCESS ON DATABASE kgproduit TO cdc_reader;
GRANT ACCESS ON DATABASE kgprojet TO cdc_reader;
GRANT EXECUTE BOOSTED PROCEDURE db.cdc.* ON DBMS TO cdc_reader;

// KG curator: write access to the KGs, reserved for approved tool effects (never exposed to agents).
CREATE ROLE kg_curator IF NOT EXISTS;
CREATE USER kgcurator IF NOT EXISTS SET PASSWORD $kgPw CHANGE NOT REQUIRED;
GRANT ROLE kg_curator TO kgcurator;
GRANT ACCESS ON DATABASE kgproduit TO kg_curator;
GRANT MATCH {*} ON GRAPH kgproduit TO kg_curator;
GRANT WRITE ON GRAPH kgproduit TO kg_curator;
GRANT NAME MANAGEMENT ON DATABASE kgproduit TO kg_curator;
