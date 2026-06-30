import argparse
import os
import sys
from dotenv import load_dotenv

from knowledge_map.adapters.sqlite_db import SQLiteStatusTracker
from knowledge_map.adapters.neo4j_db import Neo4jAdapter, Neo4jConfigError, Neo4jConnectionError
from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter, get_embedding_embedder, cosine_similarity
from knowledge_map.adapters.coreference import PydanticAICoreferenceAdapter
from knowledge_map.adapters.extraction import PydanticAIEntityExtractionAdapter
from knowledge_map.adapters.dlq import LocalFileDLQAdapter
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.core.ingestion import BatchIngestionService

def main(args=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="California Political Influence GraphRAG Engine - Production CLI"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Ingest subcommand
    ingest_parser = subparsers.add_parser("ingest", help="Run batch ingestion of unprocessed articles")
    ingest_parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without saving to Neo4j")

    # Clear subcommand
    subparsers.add_parser("clear", help="Clear all nodes and relationships from Neo4j")

    # Analyze subcommand
    subparsers.add_parser("analyze", help="Inspect and list distinct node labels in the Neo4j database")

    parsed_args = parser.parse_args(args)

    if parsed_args.action == "ingest":
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")

        db_adapter = None
        try:
            if parsed_args.dry_run:
                db_adapter = Neo4jAdapter(
                    uri=uri or "bolt://localhost:7687",
                    username=username or "neo4j",
                    password=password or "password"
                )
            else:
                db_adapter = Neo4jAdapter(uri=uri, username=username, password=password)

            embedding_adapter = PydanticAIEmbeddingAdapter()
            coreference_adapter = PydanticAICoreferenceAdapter()
            extraction_adapter = PydanticAIEntityExtractionAdapter()
            dlq_adapter = LocalFileDLQAdapter()
            status_tracker = SQLiteStatusTracker()

            pipeline = StoryPipeline(
                db_adapter=db_adapter,
                embedding_adapter=embedding_adapter,
                coreference_adapter=coreference_adapter,
                extraction_adapter=extraction_adapter,
                status_tracker=status_tracker,
                dlq_adapter=dlq_adapter
            )

            service = BatchIngestionService(pipeline=pipeline)
            service.run()

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
            if db_adapter:
                db_adapter.close()

    elif parsed_args.action == "clear":
        uri = os.environ.get("NEO4J_URI")
        username = os.environ.get("NEO4J_USERNAME")
        password = os.environ.get("NEO4J_PASSWORD")

        manager = None
        try:
            manager = Neo4jAdapter(uri=uri, username=username, password=password)
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
            manager = Neo4jAdapter(uri=uri, username=username, password=password)
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

if __name__ == "__main__":
    main()
