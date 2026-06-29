import argparse
import os
import sys
import re
import math
from dotenv import load_dotenv
from neo4j import GraphDatabase
from extraction import extract_entities
from schemas import ExtractionResult
from db import get_last_n_stories, get_all_stories
from pydantic_ai import Embedder
from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
from pydantic_ai.providers.openai import OpenAIProvider
from coreference import resolve_coreferences, replace_tags_with_entities
from chunking import chunk_article
import asyncio
from config import settings

class Neo4jConfigError(ValueError):
    """Raised when Neo4j configuration is missing or invalid."""
    pass

class Neo4jConnectionError(Exception):
    """Raised when there is an error connecting to or interacting with Neo4j."""
    pass

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if len(v1) != len(v2):
        raise ValueError("Vectors must be of the same dimension.")
    dot_product = sum(x * y for x, y in zip(v1, v2))
    mag1 = math.sqrt(sum(x * x for x in v1))
    mag2 = math.sqrt(sum(x * x for x in v2))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return dot_product / (mag1 * mag2)

def get_embedding_embedder() -> Embedder:
    load_dotenv()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_embedding_model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "embeddinggemma")
    
    provider = OpenAIProvider(
        base_url=f"{ollama_base_url}/v1",
        api_key="ollama",
    )
    
    model = OpenAIEmbeddingModel(
        ollama_embedding_model,
        provider=provider,
    )
    
    return Embedder(model)

IDENTIFIER_REGEX = re.compile(r"^[A-Za-z0-9_]+$")

def ingest_extraction_result(tx, extraction: ExtractionResult, source_url: str | None = None):
    node_labels = {}
    for node in extraction.nodes:
        label = node.label
        if not IDENTIFIER_REGEX.match(label):
            raise ValueError(f"Invalid character in node label: {label}")
        node_labels[node.name] = label
        query = f"MERGE (n:{label} {{name: $name}}) SET n.source_url = $source_url, n += $properties"
        tx.run(query, name=node.name, source_url=source_url, properties=node.properties)

    for rel in extraction.relationships:
        rel_type = rel.relationship_type
        if not IDENTIFIER_REGEX.match(rel_type):
            raise ValueError(f"Invalid character in relationship type: {rel_type}")
        
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

class Neo4jManager:
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
        except Exception as e:
            raise Neo4jConnectionError(f"Could not connect to Neo4j database: {e}")
        
        if not self._index_ensured:
            self._ensure_vector_index()
            self._index_ensured = True
        
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

    def ingest_article(self, url: str, title: str | None = None, author: str | None = None, published_date: str | None = None) -> None:
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    query = """
                    MERGE (a:Article {url: $url})
                    SET a.title = $title, a.author = $author, a.published_date = $published_date
                    """
                    tx.run(query, url=url, title=title, author=author, published_date=published_date)
                session.execute_write(_tx)
        except Exception as e:
            raise Neo4jConnectionError(f"Failed to ingest Article to Neo4j: {e}")

    def ingest_chunk(self, url: str, chunk_id: str, text: str, chunk_index: int, embedding: list[float]) -> None:
        driver = self.connect()
        try:
            with driver.session() as session:
                def _tx(tx):
                    query = """
                    MATCH (a:Article {url: $url})
                    MERGE (c:Chunk {id: $chunk_id})
                    SET c.text = $text, c.chunk_index = $chunk_index, c.embedding = $embedding
                    MERGE (c)-[:BELONGS_TO]->(a)
                    """
                    tx.run(query, url=url, chunk_id=chunk_id, text=text, chunk_index=chunk_index, embedding=embedding)
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
                        if not IDENTIFIER_REGEX.match(label):
                            raise ValueError(f"Invalid character in node label: {label}")
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
                        if not IDENTIFIER_REGEX.match(rel_type):
                            raise ValueError(f"Invalid character in relationship type: {rel_type}")
                        
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
        if not IDENTIFIER_REGEX.match(label):
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
            self._driver.close()
            self._driver = None

def process_story(
    manager: Neo4jManager | None,
    story: dict,
    dry_run: bool = False
) -> None:
    content = story.get("content") or ""
    url = story.get("url") or "http://example.com/text-input"
    title = story.get("title")
    author = story.get("author")
    published_date = story.get("published_date")

    print(f"Resolving coreferences for story: {title or url}")
    annotated_text = resolve_coreferences(content)
    clean_text = replace_tags_with_entities(annotated_text)

    print("Chunking story content...")
    chunks = chunk_article(clean_text)
    print(f"Split into {len(chunks)} chunk(s).")

    print("Generating vector embeddings...")
    embedder = get_embedding_embedder()
    chunk_texts = [c.text for c in chunks]
    if chunk_texts:
        res = asyncio.run(embedder.embed_documents(chunk_texts))
        embeddings = res.embeddings
    else:
        embeddings = []

    if not dry_run:
        if not manager:
            raise Neo4jConfigError("Neo4jManager not provided for non-dry-run mode.")
        print(f"Ingesting Article node into Neo4j: {url}")
        manager.ingest_article(
            url=url,
            title=title,
            author=author,
            published_date=published_date
        )

    for idx, chunk in enumerate(chunks):
        chunk_id = f"{url}#chunk_{idx}"
        embedding = embeddings[idx] if idx < len(embeddings) else []

        if dry_run:
            print(f"\n--- Chunk {idx} (Dry Run) ---")
            print(f"Chunk ID: {chunk_id}")
            print(f"Chunk text snippet: {chunk.text[:120]}...")
            print("Extracting entities...")
            result = extract_entities(chunk.text)
            print("Validated Extraction Result (JSON):")
            print(result.model_dump_json(indent=2))
        else:
            print(f"Ingesting Chunk {idx} node into Neo4j...")
            manager.ingest_chunk(
                url=url,
                chunk_id=chunk_id,
                text=chunk.text,
                chunk_index=idx,
                embedding=embedding
            )
            print(f"Extracting entities from Chunk {idx}...")
            result = extract_entities(chunk.text)
            print(f"Ingesting extraction for Chunk {idx} into Neo4j...")
            manager.ingest_chunk_extraction(
                chunk_id=chunk_id,
                extraction=result
            )

def main(args=None):
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="CA Political Influence GraphRAG Engine - Playground"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("clear", help="Clear all nodes and relationships from Neo4j")
    subparsers.add_parser("analyze", help="Inspect and list distinct node labels in the Neo4j database")
    
    run_parser = subparsers.add_parser("run", help="Run entity extraction")
    run_parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without saving to Neo4j")
    run_parser.add_argument("--text", type=str, help="Process this text instead of the database content")
    
    parsed_args = parser.parse_args(args)
    
    if parsed_args.action == "clear":
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")
        
        manager = None
        try:
            manager = Neo4jManager(uri=uri, username=username, password=password)
            manager.clear_database()
            print("Neo4j database cleared successfully.")
        except Neo4jConfigError as e:
            print(f"Configuration Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Neo4jConnectionError as e:
            print(f"Connection Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            if manager:
                manager.close()
    elif parsed_args.action == "analyze":
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")
        
        manager = None
        try:
            manager = Neo4jManager(uri=uri, username=username, password=password)
            labels = manager.get_distinct_labels()
            if labels:
                print("Distinct node labels:")
                for label in labels:
                    print(f"- {label}")
                
                embedder = None
                for label in labels:
                    nodes = manager.get_nodes_by_label(label)
                    if len(nodes) >= 2:
                        if embedder is None:
                            embedder = get_embedding_embedder()
                        import asyncio
                        res = asyncio.run(embedder.embed_documents(nodes))
                        embeddings = res.embeddings
                        
                        duplicates = []
                        for i in range(len(nodes)):
                            for j in range(i + 1, len(nodes)):
                                sim = cosine_similarity(embeddings[i], embeddings[j])
                                if sim > 0.85:
                                    duplicates.append((nodes[i], nodes[j], sim))
                        
                        if duplicates:
                            print(f"\nPotential duplicates in label '{label}':")
                            for n1, n2, sim in duplicates:
                                print(f"- '{n1}' and '{n2}' (Similarity: {sim:.2f})")
            else:
                print("No node labels found in the database.")
        except Neo4jConfigError as e:
            print(f"Configuration Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Neo4jConnectionError as e:
            print(f"Connection Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            if manager:
                manager.close()
    elif parsed_args.action == "run":
        if parsed_args.dry_run:
            story = {}
            if parsed_args.text:
                story = {
                    "content": parsed_args.text,
                    "url": "http://example.com/text-input",
                    "title": "Text Input",
                }
            else:
                stories = get_last_n_stories(1)
                if stories and stories[0].get("content"):
                    story = stories[0]
                else:
                    story = {
                        "content": (
                            "Governor Gavin Newsom signed Assembly Bill 5 (AB-5) into law today, "
                            "a major public policy measure supported by the California Labor Federation. "
                            "The legislation was heavily opposed by the California Chamber of Commerce "
                            "and several gig economy corporations, including Uber and Lyft."
                        ),
                        "url": "http://example.com/fallback-story",
                        "title": "Fallback Story",
                        "author": "System",
                        "published_date": "2026-06-28",
                    }
            
            print("Starting chunked extraction pipeline dry-run...")
            try:
                process_story(manager=None, story=story, dry_run=True)
            except Exception as e:
                print(f"Extraction failed: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            uri = os.environ.get("NEO4J_URI")
            username = os.environ.get("NEO4J_USERNAME")
            password = os.environ.get("NEO4J_PASSWORD")
            
            manager = None
            try:
                manager = Neo4jManager(uri=uri, username=username, password=password)
                
                if parsed_args.text:
                    story = {
                        "content": parsed_args.text,
                        "url": "http://example.com/text-input",
                        "title": "Text Input",
                    }
                    print("Processing provided text through the pipeline...")
                    process_story(manager, story, dry_run=False)
                    print("Successfully processed 1 story")
                else:
                    stories = get_all_stories()
                    if not stories:
                        print("No stories with content found in SQLite database.")
                        return
                    
                    print(f"Found {len(stories)} stories to process.")
                    for i, story in enumerate(stories, 1):
                        print(f"[{i}/{len(stories)}] Processing story '{story['title']}'...")
                        try:
                            process_story(manager, story, dry_run=False)
                        except Exception as e:
                            print(f"Failed to process story '{story['title']}': {e}", file=sys.stderr)
                            raise
                    print(f"Successfully processed {len(stories)} stories")
                    
            except Neo4jConfigError as e:
                print(f"Configuration Error: {e}", file=sys.stderr)
                sys.exit(1)
            except Neo4jConnectionError as e:
                print(f"Connection Error: {e}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Unexpected Error: {e}", file=sys.stderr)
                sys.exit(1)
            finally:
                if manager:
                    manager.close()

if __name__ == "__main__":
    main()
