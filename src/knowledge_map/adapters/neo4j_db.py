import re
from neo4j import GraphDatabase
from knowledge_map.schemas import ExtractionResult, SourceArticle, ArticleChunk
from knowledge_map.config import settings

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
        query = f"MERGE (n:{label} {{name: $name}}) SET n.source_url = $source_url, n += $properties"
        tx.run(query, name=node.name, source_url=source_url, properties=node.properties)

    for rel in extraction.relationships:
        rel_type = rel.relationship_type
        
        src_label = node_labels.get(rel.source, "")
        tgt_label = node_labels.get(rel.target, "")
        
        src_clause = f":{src_label}" if src_label else ""
        tgt_clause = f":{tgt_label}" if tgt_label else ""
        
        query = (
            f"MATCH (src{src_clause} {{name: $src_name}}), (tgt{tgt_clause} {{name: $tgt_name}}) "
            f"MERGE (src)-[r:{rel_type}]->(tgt) "
            f"SET r += $properties"
        )
        tx.run(query, src_name=rel.source, tgt_name=rel.target, properties=rel.properties)

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
                    query = """
                    MERGE (a:Article {url: $url})
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
                    MATCH (a:Article {url: $url})
                    MERGE (c:Chunk {id: $chunk_id})
                    SET c.text = $text, c.chunk_index = $chunk_index, c.embedding = $embedding
                    MERGE (c)-[:BELONGS_TO]->(a)
                    """
                    tx.run(
                        query,
                        url=article.url,
                        chunk_id=chunk_id,
                        text=chunk.text,
                        chunk_index=chunk.index,
                        embedding=embedding
                    )
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest Chunk to Neo4j: {e}")

    def ingest_chunk_extraction(self, chunk_id: str, extraction: ExtractionResult) -> None:
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    node_labels = {}
                    for node in extraction.nodes:
                        label = node.label
                        node_labels[node.name] = label
                        
                        # Merge node
                        query = f"MERGE (n:{label} {{name: $name}}) SET n += $properties"
                        tx.run(query, name=node.name, properties=node.properties)
                        
                        # Connect node to chunk: (Entity)-[:MENTIONED_IN]->(Chunk)
                        mention_query = f"""
                        MATCH (c:Chunk {{id: $chunk_id}}), (n:{label} {{name: $name}})
                        MERGE (n)-[:MENTIONED_IN]->(c)
                        """
                        tx.run(mention_query, chunk_id=chunk_id, name=node.name)

                    for rel in extraction.relationships:
                        rel_type = rel.relationship_type
                        
                        src_label = node_labels.get(rel.source, "")
                        tgt_label = node_labels.get(rel.target, "")
                        
                        src_clause = f":{src_label}" if src_label else ""
                        tgt_clause = f":{tgt_label}" if tgt_label else ""
                        
                        query = (
                            f"MATCH (src{src_clause} {{name: $src_name}}), (tgt{tgt_clause} {{name: $tgt_name}}) "
                            f"MERGE (src)-[r:{rel_type}]->(tgt) "
                            f"SET r.source_chunk_id = $chunk_id, r += $properties"
                        )
                        tx.run(query, src_name=rel.source, tgt_name=rel.target, chunk_id=chunk_id, properties=rel.properties)
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

