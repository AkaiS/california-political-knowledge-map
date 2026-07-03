import argparse
import os
import sys
import json
import logging
import asyncio
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

from knowledge_map.config import settings
from knowledge_map.adapters.sqlite_db import SQLiteStatusTracker, register_publication
from knowledge_map.core.bootstrapper import bootstrap_publication_stub
from knowledge_map.core.discovery import ListingPageDiscoveryService
from knowledge_map.adapters.neo4j_db import Neo4jAdapter, Neo4jConfigError, Neo4jConnectionError
from knowledge_map.adapters.embedding import PydanticAIEmbeddingAdapter, get_embedding_embedder, cosine_similarity
from knowledge_map.adapters.coreference import PydanticAICoreferenceAdapter
from knowledge_map.adapters.extraction import PydanticAIEntityExtractionAdapter
from knowledge_map.adapters.dlq import LocalFileDLQAdapter
from knowledge_map.core.pipeline import StoryPipeline
from knowledge_map.core.ingestion import BatchIngestionService
from knowledge_map.utils.console import ConsoleNotifier
from knowledge_map.core.exceptions import PipelineLockError
from knowledge_map.utils.telemetry import setup_telemetry

def setup_logging(log_file_path: str = ".scratch/pipeline.log", log_level: int = logging.INFO):
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    # Console Handler
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File Handler
    file_handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s")
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Logfire Handler
    try:
        import logfire
        root_logger.addHandler(logfire.LogfireLoggingHandler())
    except ImportError:
        pass

def main(args=None):
    load_dotenv()
    setup_telemetry()
    setup_logging()

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

    # Janitor subcommand
    subparsers.add_parser("janitor", help="Perform a health check on the locked component and release lock if healthy")

    # Register-publication subcommand
    register_parser = subparsers.add_parser("register-publication", help="Register a new Publication in the database")
    register_parser.add_argument("--id", required=True, help="Unique publication identifier (e.g. 'calmatters')")
    register_parser.add_argument("--name", required=True, help="Human-readable publication name (e.g. 'CalMatters')")
    register_parser.add_argument("--base-url", required=True, help="Base URL of the publication (e.g. 'https://calmatters.org')")
    register_parser.add_argument("--crawl-delay", type=float, default=2.0, help="Crawl delay in seconds")
    register_parser.add_argument("--max-concurrency", type=int, default=2, help="Maximum concurrent requests")
    register_parser.add_argument("--use-robots-txt", action="store_true", default=True, help="Respect robots.txt (default)")
    register_parser.add_argument("--no-robots-txt", action="store_false", dest="use_robots_txt", help="Do not respect robots.txt")
    register_parser.add_argument("--discovery-config-json", help="JSON string of discovery configuration parameters")
    register_parser.add_argument("--archive-cutoff-years", type=int, default=5, help="Number of years of historical archive to crawl")

    # Update-sources subcommand
    subparsers.add_parser("update-sources", help="Run incremental scraping/discovery for registered publications")

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
            sys.exit(0)

        except PipelineLockError as e:
            lock_path = settings.batch_ingestion.lock_file_path
            component = "unknown"
            timestamp = "unknown"
            error_message = str(e)
            if os.path.exists(lock_path):
                try:
                    with open(lock_path, "r") as f:
                        data = json.load(f)
                        component = data.get("component", "unknown")
                        timestamp = data.get("timestamp", "unknown")
                        error_message = data.get("error_message", str(e))
                except Exception:
                    pass
            ConsoleNotifier.notify_lock_detected(
                component=component,
                lock_file_path=lock_path,
                timestamp=timestamp,
                error_message=error_message
            )
            sys.exit(1)
        except Neo4jConfigError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Configuration Error",
                message="Neo4j Configuration is invalid.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Neo4jConnectionError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Connection Error",
                message="Failed to connect to Neo4j database.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Exception as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Unexpected Error",
                message="An unexpected system failure occurred.",
                details={"Error": str(e)}
            )
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
            sys.exit(0)
        except Neo4jConfigError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Configuration Error",
                message="Neo4j Configuration is invalid.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Neo4jConnectionError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Connection Error",
                message="Failed to connect to Neo4j database.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Exception as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Unexpected Error",
                message="An unexpected system failure occurred.",
                details={"Error": str(e)}
            )
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
            sys.exit(0)
        except Neo4jConfigError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Configuration Error",
                message="Neo4j Configuration is invalid.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Neo4jConnectionError as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Connection Error",
                message="Failed to connect to Neo4j database.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        except Exception as e:
            ConsoleNotifier.notify_critical_failure(
                error_title="Unexpected Error",
                message="An unexpected system failure occurred.",
                details={"Error": str(e)}
            )
            sys.exit(1)
        finally:
            if manager:
                manager.close()

    elif parsed_args.action == "janitor":
        lock_file_path = settings.batch_ingestion.lock_file_path
        
        if not os.path.exists(lock_file_path):
            print("No active pipeline lock found. Exiting.")
            sys.exit(0)
            
        try:
            with open(lock_file_path, "r") as f:
                lock_data = json.load(f)
        except Exception as e:
            print(f"Error reading lock file: {e}", file=sys.stderr)
            sys.exit(1)
            
        component = lock_data.get("component")
        if not component:
            print("Error: lock file does not specify 'component' key.", file=sys.stderr)
            sys.exit(1)
            
        print(f"Active lock detected due to component: '{component}'")
        
        adapter = None
        if component == "embedding":
            adapter = PydanticAIEmbeddingAdapter()
        elif component == "coreference":
            adapter = PydanticAICoreferenceAdapter()
        elif component == "extraction":
            adapter = PydanticAIEntityExtractionAdapter()
        elif component == "database":
            uri = os.environ.get("NEO4J_URI")
            username = os.environ.get("NEO4J_USERNAME")
            password = os.environ.get("NEO4J_PASSWORD")
            adapter = Neo4jAdapter(uri=uri, username=username, password=password)
        else:
            print(f"Error: Unknown component '{component}' in lock file.", file=sys.stderr)
            sys.exit(1)
            
        print(f"Running health check probe for component '{component}'...")
        try:
            is_healthy = adapter.health_check()
        except Exception as e:
            print(f"Health check probe raised an exception: {e}", file=sys.stderr)
            is_healthy = False
        finally:
            if hasattr(adapter, "close") and callable(adapter.close):
                adapter.close()
                
        if is_healthy:
            print(f"Component '{component}' health check passed! Deleting lock file...")
            try:
                os.remove(lock_file_path)
                print(f"Deleted pipeline lock file: {lock_file_path}")
                sys.exit(0)
            except Exception as e:
                print(f"Error deleting lock file: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Error: Component '{component}' health check failed. Pipeline remains locked.", file=sys.stderr)
            sys.exit(1)

    elif parsed_args.action == "register-publication":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        
        # Ensure database is initialized with publications table
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)
        
        # If discovery config json is provided, validate it's valid JSON
        discovery_config = parsed_args.discovery_config_json
        if discovery_config:
            try:
                json.loads(discovery_config)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON for discovery config: {e}", file=sys.stderr)
                sys.exit(1)
                
        try:
            register_publication(
                pub_id=parsed_args.id,
                name=parsed_args.name,
                base_url=parsed_args.base_url,
                crawl_delay=parsed_args.crawl_delay,
                max_concurrency=parsed_args.max_concurrency,
                use_robots_txt=parsed_args.use_robots_txt,
                discovery_config_json=discovery_config,
                archive_cutoff_years=parsed_args.archive_cutoff_years,
                db_path=db_path
            )
            print(f"Successfully registered publication '{parsed_args.id}'.")
            
            # Invoke the bootstrapper stub seam
            bootstrap_publication_stub(parsed_args.id)
            sys.exit(0)
        except ValueError as e:
            # Handle duplicate ID or validation errors cleanly
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected database error: {e}", file=sys.stderr)
            sys.exit(1)

    elif parsed_args.action == "update-sources":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        # Ensure database is initialized
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)
        
        service = ListingPageDiscoveryService(db_path=db_path)
        print("Starting incremental source updates...")
        results = asyncio.run(service.discover_and_scrape_all())
        has_new = False
        for pub_id, urls in results.items():
            if urls:
                has_new = True
                print(f"Scraped {len(urls)} new articles for publication '{pub_id}':")
                for url in urls:
                    print(f"  - {url}")
            else:
                print(f"No new articles scraped for publication '{pub_id}'.")
        sys.exit(0)

if __name__ == "__main__":
    main()
