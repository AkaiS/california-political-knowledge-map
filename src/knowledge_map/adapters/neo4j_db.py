import re

from neo4j import GraphDatabase

from knowledge_map.config import settings
from knowledge_map.ontology import news
from knowledge_map.ontology.keys import bill_key, derived_key
from knowledge_map.schemas import (
    ArticleChunk,
    BillSessionResolutions,
    ExtractionResult,
    LegislativeEventDates,
    Relationship,
    SourceArticle,
    TopicAssignment,
)


def _claim_key(relationship_type: str, properties: dict) -> tuple[dict, bool]:
    """The values that identify this claim, canonicalized, and whether any are missing.

    A relationship's declared properties are its Claim Key; normalization runs
    here and nowhere else.  A declared value that will not normalize is
    dropped rather than stored, and the missing flag it returns becomes the
    edge's ``needs_review``.
    """

    shape = news.RELATIONSHIPS.get(relationship_type)
    if shape is None:
        return {}, False

    key = {}
    for spec in shape.properties:
        if spec.name not in properties:
            continue
        canonical = spec.normalize(properties[spec.name])
        if canonical is not None:
            key[spec.name] = canonical
    return key, len(key) < len(shape.properties)


def _relationship_query(
    relationship_type: str, src_clause: str, tgt_clause: str, key: dict
) -> str:
    """A MERGE keyed on the claim.

    Interpolates ``relationship_type`` directly, so pass only conformed model
    output; conformance and the schema are what check it.  Key names are
    ontology-declared.
    """

    key_pattern = ""
    if key:
        key_pattern = " {" + ", ".join(f"{name}: $key_{name}" for name in sorted(key)) + "}"
    return (
        f"MATCH (src{src_clause} {{id: $src_id}}), (tgt{tgt_clause} {{id: $tgt_id}}) "
        f"MERGE (src)-[r:{relationship_type}{key_pattern}]->(tgt)"
    )


def _write_relationship(
    tx,
    rel,
    node_labels: dict,
    resolve_id,
    chunk_id: str | None = None,
) -> None:
    """The one place a relationship reaches the graph.

    Every ingestion entry point routes through here, whether the relationship
    came from an extractor or was composed from an article-level decision;
    ``resolve_id`` maps a label and a name to the node's primary key and is the
    only thing they do differently.  Pass ``chunk_id`` to accumulate the chunks
    asserting the claim, which only a per-chunk write has.

    Both endpoints are matched, never created: a relationship reaches the graph
    only once something has merged the nodes it connects.

    An edge carries only its Claim Key, those chunks, and ``needs_review``.
    Everything else the article said stays in the Article Chunk.
    """

    rel_type = rel.relationship_type

    # Conformance already resolved which node each name meant; the name map is
    # the fallback for relationships that never passed through it.
    src_label = rel.source_label or node_labels.get(rel.source, "")
    tgt_label = rel.target_label or node_labels.get(rel.target, "")

    src_clause = f":{src_label}" if src_label else ""
    tgt_clause = f":{tgt_label}" if tgt_label else ""

    key, incomplete = _claim_key(rel_type, rel.properties)

    stamps = {}
    if incomplete:
        stamps["needs_review"] = True

    query = _relationship_query(rel_type, src_clause, tgt_clause, key)
    parameters = {
        "src_id": resolve_id(src_label, rel.source),
        "tgt_id": resolve_id(tgt_label, rel.target),
        **{f"key_{name}": value for name, value in key.items()},
    }
    if stamps:
        query += " SET r += $stamps"
        parameters["stamps"] = stamps
    if chunk_id is not None:
        # The chunks that assert *this* claim. Keyed edges keep the list
        # tight; the append dedupes so re-ingesting an article is a no-op.
        query += (
            " SET r.chunks = CASE WHEN $chunk_id IN coalesce(r.chunks, []) "
            "THEN r.chunks ELSE coalesce(r.chunks, []) + $chunk_id END"
        )
        parameters["chunk_id"] = chunk_id

    tx.run(query, **parameters)


def _topic_endpoint_id(article: SourceArticle, bill_sessions: BillSessionResolutions):
    """Resolve an article-level topic edge's endpoint to a node primary key.

    The measure endpoints resolve exactly as the chunk extraction write
    resolves one, Bill Session Resolution included; the Source Article is the
    endpoint that write never has, and its URL is its key.
    """

    def resolve(label: str, name: str) -> str:
        if label == "NewsArticle":
            return article.url
        if label != "Bill":
            return derived_key(label, name)
        resolution = bill_sessions.get(name)
        return bill_key(resolution.session, resolution.name, name)

    return resolve


def _validated_labels(label: str, sub_labels: list[str]) -> str:
    """Assert the write path's own invariant on labels reaching the graph.

    Cannot fire on a conformed result; it catches an ingester that skipped
    conformance.
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
                        text=chunk.embedded_text,
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
        bill_sessions: BillSessionResolutions | None = None,
        event_dates: LegislativeEventDates | None = None,
    ) -> None:
        bill_sessions = bill_sessions or BillSessionResolutions()
        event_dates = event_dates or LegislativeEventDates()
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    # Node identity is (name, label).  This name-only map is the
                    # fallback for relationships carrying no resolved label, and
                    # keeps the last node seen.
                    node_labels: dict[str, str] = {}
                    node_ids: dict[tuple[str, str], str] = {}
                    for node in extraction.nodes:
                        label = node.label
                        node_labels[node.name] = label
                        labels = _validated_labels(label, node.sub_labels)
                        properties = dict(node.properties)
                        if label == "Bill":
                            resolution = bill_sessions.get(node.name)
                            properties.update(resolution.graph_properties())
                            # A Bill's name is its Bill Designation, or the
                            # surface string where none was recovered.
                            properties["name"] = resolution.name or node.name
                            node_id = bill_key(
                                resolution.session, resolution.name, node.name
                            )
                        else:
                            properties["name"] = node.name
                            if label == "LegislativeEvent":
                                event_date = event_dates.get(node.name)
                                if event_date is not None:
                                    properties.update(event_date.graph_properties())
                            # Name-derived, with the date deliberately outside it:
                            # one identity shape for every Legislative Event.
                            node_id = derived_key(label, node.name)
                        node_ids[(node.name, label)] = node_id

                        # Merge node
                        query = (
                            f"MERGE (n:{labels} {{id: $node_id}}) "
                            "SET n += $properties, n.id = $node_id"
                        )
                        tx.run(query, node_id=node_id, properties=properties)

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
                        node_id = node_ids.get((name, label))
                        if node_id is not None:
                            return node_id
                        if label != "Bill":
                            return derived_key(label, name)
                        resolution = bill_sessions.get(name)
                        return bill_key(resolution.session, resolution.name, name)

                    for rel in extraction.relationships:
                        _write_relationship(
                            tx, rel, node_labels, resolved_id, chunk_id=chunk_id
                        )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest chunk extraction to Neo4j: {e}")

    def ingest_article_topics(
        self,
        article: SourceArticle,
        policy_areas: list[str],
        assignments: list[TopicAssignment] | None = None,
        bill_sessions: BillSessionResolutions | None = None,
    ) -> None:
        """Write what a Source Article is about, at the level it was decided.

        A Policy Area is judged once per article, so its edge hangs off the
        Source Article rather than off any one Article Chunk, and an assignment
        carries no chunk: the article is what connects the measure to the area.

        Areas with no assignments is a normal call, not an empty case — it is
        what the pipeline hands over between classification and assignment.
        """

        assignments = assignments or []
        bill_sessions = bill_sessions or BillSessionResolutions()
        if not policy_areas and not assignments:
            return

        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    for name in policy_areas:
                        # Keyed like every non-Bill node, so the hub one
                        # article's classification writes is the node a later
                        # article reaches.
                        node_id = derived_key("PolicyArea", name)
                        tx.run(
                            "MERGE (n:PolicyArea {id: $node_id}) "
                            "SET n += $properties, n.id = $node_id",
                            node_id=node_id,
                            properties={"name": name},
                        )
                        _write_relationship(
                            tx,
                            Relationship(
                                source=article.url,
                                source_label="NewsArticle",
                                target=name,
                                target_label="PolicyArea",
                                relationship_type="DISCUSSES_TOPIC",
                            ),
                            {},
                            _topic_endpoint_id(article, bill_sessions),
                        )

                    for assignment in assignments:
                        # Both endpoints are matched, so an assignment writes
                        # an edge only where the measure was already ingested
                        # and its area was among the ones classified above.
                        _write_relationship(
                            tx,
                            Relationship(
                                source=assignment.measure_name,
                                source_label=assignment.measure_label,
                                target=assignment.policy_area,
                                target_label="PolicyArea",
                                relationship_type="ABOUT_TOPIC",
                            ),
                            {},
                            _topic_endpoint_id(article, bill_sessions),
                        )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest article topics to Neo4j: {e}")

    def clear_database(self):
        driver = self.connect()
        try:
            with driver.session() as session:
                def _clear_tx(tx):
                    tx.run("MATCH (n) DETACH DELETE n")
                session.execute_write(_clear_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to clear Neo4j database: {e}")

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
