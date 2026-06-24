import argparse
import os
import sys
import re
from dotenv import load_dotenv
from neo4j import GraphDatabase
from extraction import extract_entities, ExtractionResult
from db import get_last_n_stories, get_all_stories

class Neo4jConfigError(ValueError):
    """Raised when Neo4j configuration is missing or invalid."""
    pass

class Neo4jConnectionError(Exception):
    """Raised when there is an error connecting to or interacting with Neo4j."""
    pass

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
        rel_type = rel.type
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
        
        return self._driver

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

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None

def main(args=None):
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="CA Political Influence GraphRAG Engine - Playground"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("clear", help="Clear all nodes and relationships from Neo4j")
    
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
    elif parsed_args.action == "run":
        if parsed_args.dry_run:
            text_to_process = None
            if parsed_args.text:
                text_to_process = parsed_args.text
            else:
                stories = get_last_n_stories(1)
                if stories and stories[0].get("content"):
                    text_to_process = stories[0]["content"]
                else:
                    text_to_process = (
                        "Governor Gavin Newsom signed Assembly Bill 5 (AB-5) into law today, "
                        "a major public policy measure supported by the California Labor Federation. "
                        "The legislation was heavily opposed by the California Chamber of Commerce "
                        "and several gig economy corporations, including Uber and Lyft."
                    )
            
            print("Starting entity extraction dry-run...")
            try:
                result = extract_entities(text_to_process)
                print("\nValidated Extraction Result (JSON):")
                print(result.model_dump_json(indent=2))
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
                    print("Extracting entities from provided text...")
                    result = extract_entities(parsed_args.text)
                    print("Ingesting extracted graph into Neo4j...")
                    manager.ingest_extraction(result, source_url=None)
                    print("Successfully processed 1 story")
                else:
                    stories = get_all_stories()
                    if not stories:
                        print("No stories with content found in SQLite database.")
                        return
                    
                    print(f"Found {len(stories)} stories to process.")
                    for i, story in enumerate(stories, 1):
                        print(f"[{i}/{len(stories)}] Extracting from '{story['title']}'...")
                        try:
                            result = extract_entities(story["content"])
                            manager.ingest_extraction(result, source_url=story["url"])
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
