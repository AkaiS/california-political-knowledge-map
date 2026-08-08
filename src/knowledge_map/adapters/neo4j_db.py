import re

from neo4j import GraphDatabase

from knowledge_map.config import settings
from knowledge_map.ontology import news, primary
from knowledge_map.ontology.keys import bill_key, derived_key
from knowledge_map.schemas import ArticleChunk, ExtractionResult, SourceArticle
from knowledge_map.core.bill_sessions import normalize_bill_number

SHORTCUT_SKIPS = {
    relationship_type: shortcut.skips
    for relationship_type, shortcut in news.SHORTCUTS_BY_TYPE.items()
}


def _normalized_properties(relationship_type: str, properties: dict) -> dict:
    """Canonicalize declared properties; pass everything else through untouched.

    A declared property whose value will not normalize is dropped rather than
    stored: keeping ``"a lot"`` alongside ``6000000.0`` in the same field is what
    makes two articles look like they disagree when only one of them was legible.
    """

    shape = primary.RELATIONSHIPS.get(relationship_type)
    if shape is None:
        return dict(properties)

    normalized = {}
    for name, value in properties.items():
        spec = shape.spec(name)
        if spec is None:
            normalized[name] = value
            continue
        canonical = spec.normalize(value)
        if canonical is not None:
            normalized[name] = canonical
    return normalized


def _claim_key(relationship_type: str, properties: dict) -> tuple[dict, bool]:
    """The identifying values that pin this claim, and whether any are missing.

    Two edges of the same type between the same pair are the same edge only when
    their claim keys match. An incomplete key is not padded with nulls — Neo4j
    stores no nulls and would never match one — so the edge merges on what it has
    and carries `needs_review` to say the comparison is not yet possible.
    """

    identifying = news.IDENTIFYING_PROPERTIES.get(relationship_type, frozenset())
    key = {name: properties[name] for name in sorted(identifying) if name in properties}
    return key, len(key) < len(identifying)


def _relationship_query(
    relationship_type: str, src_clause: str, tgt_clause: str, key: dict
) -> str:
    """A MERGE keyed on the claim. Key names come from the ontology, never from input."""

    key_pattern = ""
    if key:
        key_pattern = " {" + ", ".join(f"{name}: $key_{name}" for name in sorted(key)) + "}"
    return (
        f"MATCH (src{src_clause} {{id: $src_id}}), (tgt{tgt_clause} {{id: $tgt_id}}) "
        f"MERGE (src)-[r:{relationship_type}{key_pattern}]->(tgt) "
        f"SET r += $properties"
    )


def _write_relationship(
    tx,
    rel,
    node_labels: dict,
    resolve_id,
    chunk_id: str | None = None,
) -> None:
    """The one place an extractor-produced relationship reaches the graph.

    Both ingestion entry points route through here, so a change to edge
    semantics cannot land in one path and miss the other. ``resolve_id`` maps a
    label and a name to the node's primary key, which is the only thing the two
    entry points do differently. When ``chunk_id`` is given the edge also
    accumulates the chunks that assert this claim.
    """

    rel_type = rel.relationship_type

    src_label = node_labels.get(rel.source, "")
    tgt_label = node_labels.get(rel.target, "")

    src_clause = f":{src_label}" if src_label else ""
    tgt_clause = f":{tgt_label}" if tgt_label else ""

    rel_properties = _normalized_properties(rel_type, rel.properties)
    if rel_type in SHORTCUT_SKIPS:
        rel_properties["skips"] = SHORTCUT_SKIPS[rel_type]
    key, incomplete = _claim_key(rel_type, rel_properties)
    if incomplete:
        rel_properties["needs_review"] = True

    query = _relationship_query(rel_type, src_clause, tgt_clause, key)
    parameters = {
        "src_id": resolve_id(src_label, rel.source),
        "tgt_id": resolve_id(tgt_label, rel.target),
        "properties": rel_properties,
        **{f"key_{name}": value for name, value in key.items()},
    }
    if chunk_id is not None:
        # The chunks that assert *this* claim. Keyed edges keep the list
        # tight; the append dedupes so re-ingesting an article is a no-op.
        query += (
            " SET r.chunks = CASE WHEN $chunk_id IN coalesce(r.chunks, []) "
            "THEN r.chunks ELSE coalesce(r.chunks, []) + $chunk_id END"
        )
        parameters["chunk_id"] = chunk_id

    tx.run(query, **parameters)


def _validated_labels(label: str, sub_labels: list[str]) -> str:
    """Assert the write path's own invariant on labels reaching the graph.

    Extraction conformance already gates model output on the same
    extracted-label subset, so this cannot fire on a conformed result. It stays
    as an internal invariant: an ingester that skipped conformance fails here
    rather than writing an off-ontology node.
    """
    if label not in news.EXTRACTED_LABELS:
        raise ValueError(f"Invalid extracted node label: {label}")
    allowed = news.SUB_LABELS.get(label, frozenset())
    invalid = set(sub_labels) - allowed
    if invalid:
        raise ValueError(f"Invalid sub-label for {label}: {min(invalid)}")
    return ":".join((label, *sub_labels))

class Neo4jConfigError(ValueError):
    """Raised when Neo4j configuration is missing or invalid."""
    pass

class Neo4jConnectionError(Exception):
    """Raised when there is an error connecting to or interacting with Neo4j."""
    pass
def ingest_extraction_result(tx, extraction: ExtractionResult, source_url: str | None = None):
    node_labels = {}
    for node in extraction.nodes:
        label = node.label
        node_labels[node.name] = label
        labels = _validated_labels(label, node.sub_labels)
        node_id = derived_key(label, node.name)
        query = (
            f"MERGE (n:{labels} {{id: $node_id}}) "
            "SET n += $properties, n.id = $node_id, n.name = $name, n.source_url = $source_url"
        )
        tx.run(query, node_id=node_id, name=node.name, source_url=source_url,
               properties=node.properties)

    for rel in extraction.relationships:
        _write_relationship(tx, rel, node_labels, derived_key)

class Neo4jAdapter:
    def __init__(self, uri: str | None, username: str | None, password: str | None, driver=None):
        if not uri:
            raise Neo4jConfigError("NEO4J_URI environment variable is missing or empty.")
        if not username:
            raise Neo4jConfigError("NEO4J_USERNAME environment variable is missing or empty.")
        if not password:
            raise Neo4jConfigError("NEO4J_PASSWORD environment variable is missing or empty.")
        self.uri = uri
        self.username = username
        self.password = password
        self._driver = driver
        self._index_ensured = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self):
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.username, self.password)
                )
            except Exception as e:
                raise Neo4jConnectionError(f"Could not connect to Neo4j database: {e}")
        
        try:
            self._driver.verify_connectivity()
            if not self._index_ensured:
                self._ensure_vector_index()
                self._index_ensured = True
        except Exception as e:
            self.close()
            if isinstance(e, Neo4jConnectionError):
                raise
            raise Neo4jConnectionError(f"Could not connect to Neo4j database: {e}")
        
        return self._driver

    def _ensure_vector_index(self):
        dimension = settings.embedding.dimension
        try:
            with self._driver.session() as session:
                query = f"""
                CREATE VECTOR INDEX chunk_vector_index IF NOT EXISTS
                FOR (c:Chunk)
                ON (c.embedding)
                OPTIONS {{
                  indexConfig: {{
                    `vector.dimensions`: {dimension},
                    `vector.similarity_function`: 'cosine'
                  }}
                }}
                """
                session.run(query)
                
                result = session.run("SHOW INDEXES YIELD name WHERE name = 'chunk_vector_index'")
                exists = result.peek() is not None
                if not exists:
                    raise Neo4jConnectionError("Vector index 'chunk_vector_index' was not created successfully.")
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to create or verify vector index: {e}")

    def ingest_article(self, article: SourceArticle) -> None:
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    # The article URL is the NewsArticle primary key; see ontology.md.
                    query = """
                    MERGE (a:NewsArticle {id: $url})
                    SET a.title = $title, a.author = $author, a.published_date = $published_date
                    """
                    tx.run(
                        query,
                        url=article.url,
                        title=article.title,
                        author=article.author,
                        published_date=article.published_date
                    )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest Article to Neo4j: {e}")

    def ingest_chunk(
        self,
        article: SourceArticle,
        chunk: ArticleChunk,
        embedding: list[float]
    ) -> None:
        driver = self.connect()
        chunk_id = f"{article.url}#chunk_{chunk.index}"
        try:
            with driver.session() as session:
                def _tx(tx):
                    query = """
                    MATCH (a:NewsArticle {id: $url})
                    MERGE (c:Chunk {id: $chunk_id})
                    SET c.text = $text, c.index = $index, c.embedding = $embedding
                    MERGE (a)-[:HAS_CHUNK]->(c)
                    """
                    tx.run(
                        query,
                        url=article.url,
                        chunk_id=chunk_id,
                        text=chunk.text,
                        index=chunk.index,
                        embedding=embedding,
                    )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest Chunk to Neo4j: {e}")

    def ingest_chunk_extraction(
        self,
        chunk_id: str,
        extraction: ExtractionResult,
        bill_sessions: dict[str, dict[str, object]] | None = None,
    ) -> None:
        bill_sessions = bill_sessions or {}
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    node_labels = {}
                    node_ids = {}
                    for node in extraction.nodes:
                        label = node.label
                        node_labels[node.name] = label
                        labels = _validated_labels(label, node.sub_labels)
                        properties = dict(node.properties)
                        if label == "Bill":
                            number = normalize_bill_number(properties.get("number") or node.name)
                            resolution = bill_sessions.get(number or "", {})
                            properties.update(resolution)
                            if number:
                                properties["number"] = number
                            node_id = bill_key(resolution.get("session"), number, node.name)
                        else:
                            node_id = derived_key(label, node.name)
                        node_ids[node.name] = node_id

                        # Merge node
                        query = (
                            f"MERGE (n:{labels} {{id: $node_id}}) "
                            "SET n += $properties, n.id = $node_id, n.name = $name"
                        )
                        tx.run(query, node_id=node_id, name=node.name, properties=properties)

                        # Connect node to chunk: (Entity)-[:MENTIONED_IN]->(Chunk)
                        mention_query = f"""
                        MATCH (c:Chunk {{id: $chunk_id}}), (n:{label} {{id: $node_id}})
                        MERGE (n)-[:MENTIONED_IN]->(c)
                        """
                        tx.run(mention_query, chunk_id=chunk_id, node_id=node_id)

                        if label == "PolicyArea":
                            topic_query = """
                            MATCH (c:Chunk {id: $chunk_id}), (n:PolicyArea {id: $node_id})
                            MERGE (c)-[:DISCUSSES_TOPIC]->(n)
                            """
                            tx.run(topic_query, chunk_id=chunk_id, node_id=node_id)

                    def resolved_id(label: str, name: str) -> str:
                        if name in node_ids:
                            return node_ids[name]
                        if label != "Bill":
                            return derived_key(label, name)
                        number = normalize_bill_number(name)
                        resolution = bill_sessions.get(number or "", {})
                        return bill_key(resolution.get("session"), number, name)

                    for rel in extraction.relationships:
                        _write_relationship(
                            tx, rel, node_labels, resolved_id, chunk_id=chunk_id
                        )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest chunk extraction to Neo4j: {e}")

    def clear_database(self):
        driver = self.connect()
        try:
            with driver.session() as session:
                def _clear_tx(tx):
                    tx.run("MATCH (n) DETACH DELETE n")
                session.execute_write(_clear_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to clear Neo4j database: {e}")

    def ingest_extraction(self, extraction: ExtractionResult, source_url: str | None = None):
        driver = self.connect()
        try:
            with driver.session() as session:
                def _ingest_tx(tx):
                    ingest_extraction_result(tx, extraction, source_url)
                session.execute_write(_ingest_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest extraction result to Neo4j: {e}")

    def get_distinct_labels(self):
        driver = self.connect()
        try:
            with driver.session() as session:
                def _get_labels_tx(tx):
                    result = tx.run("CALL db.labels() YIELD label RETURN label")
                    return [record["label"] for record in result]
                labels = session.execute_read(_get_labels_tx)
                return sorted(labels)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to retrieve node labels from Neo4j: {e}")

    def get_nodes_by_label(self, label: str):
        if not re.match(r"^[A-Za-z0-9_]+$", label):
            raise ValueError(f"Invalid character in node label: {label}")
        driver = self.connect()
        try:
            with driver.session() as session:
                def _get_nodes_tx(tx):
                    result = tx.run(f"MATCH (n:{label}) RETURN n.name as name")
                    return [record["name"] for record in result]
                return session.execute_read(_get_nodes_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to retrieve nodes for label '{label}': {e}")

    def close(self):
        if self._driver is not None:
            try:
                self._driver.close()
            finally:
                self._driver = None

    def health_check(self) -> bool:
        try:
            driver = self.connect()
            with driver.session() as session:
                result = session.run("RETURN 1")
                val = result.single()[0]
                return val == 1
        except Exception:
            return False
