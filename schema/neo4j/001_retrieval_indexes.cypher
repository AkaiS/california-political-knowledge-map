// Retrieval indexes installed once when the databases are set up. Neo4j keeps
// their contents current as nodes and properties change.

CREATE FULLTEXT INDEX entity_name_fulltext_index IF NOT EXISTS
FOR (n:Bill|Campaign|Committee|LegislativeEvent|Organization|PolicyArea|Politician|Prop)
ON EACH [n.name];

CREATE FULLTEXT INDEX article_title_fulltext_index IF NOT EXISTS
FOR (n:NewsArticle)
ON EACH [n.title];

CREATE FULLTEXT INDEX chunk_text_fulltext_index IF NOT EXISTS
FOR (n:Chunk)
ON EACH [n.text];

CREATE RANGE INDEX bill_id_index IF NOT EXISTS
FOR (n:Bill) ON (n.id);

CREATE RANGE INDEX campaign_id_index IF NOT EXISTS
FOR (n:Campaign) ON (n.id);

CREATE RANGE INDEX committee_id_index IF NOT EXISTS
FOR (n:Committee) ON (n.id);

CREATE RANGE INDEX legislativeevent_id_index IF NOT EXISTS
FOR (n:LegislativeEvent) ON (n.id);

CREATE RANGE INDEX organization_id_index IF NOT EXISTS
FOR (n:Organization) ON (n.id);

CREATE RANGE INDEX policyarea_id_index IF NOT EXISTS
FOR (n:PolicyArea) ON (n.id);

CREATE RANGE INDEX politician_id_index IF NOT EXISTS
FOR (n:Politician) ON (n.id);

CREATE RANGE INDEX prop_id_index IF NOT EXISTS
FOR (n:Prop) ON (n.id);

CREATE RANGE INDEX newsarticle_id_index IF NOT EXISTS
FOR (n:NewsArticle) ON (n.id);

CREATE RANGE INDEX chunk_id_index IF NOT EXISTS
FOR (n:Chunk) ON (n.id);

CREATE VECTOR INDEX chunk_vector_index IF NOT EXISTS
FOR (n:Chunk)
ON (n.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CALL db.awaitIndexes(30);
