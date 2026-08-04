import argparse
import os
import sys
import json
import logging
import asyncio
import sqlite3
import datetime
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import structlog

from knowledge_map.config import settings
from knowledge_map.adapters.sqlite_db import SQLiteStatusTracker, register_publication, update_publication
from knowledge_map.core.bootstrapper import bootstrap_publication_stub
from knowledge_map.core.discovery import ListingPageDiscoveryService, ArchiveDiscoveryService
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


CLI_COMMAND_HELP = {
    "ingest": "Run batch ingestion of unprocessed articles",
    "clear": "Clear all nodes and relationships from Neo4j",
    "analyze": "Inspect and list distinct node labels in the Neo4j database",
    "janitor": "Perform a health check on the locked component and release lock if healthy",
    "register-publication": "Register a new Publication in the database",
    "update-publication": "Update an existing Publication in the database",
    "update-sources": "Run incremental scraping/discovery for registered publications",
    "scrape-archive": "Run archive crawl using DomainMapper",
    "refetch-html": "Refetch raw HTML for relevant articles that need extraction",
    "validate-articles": "Run validation on pending articles in raw HTML cache",
    "review-selectors": "Review unresolved selector proposals and promote/reject them",
    "heal-selectors": "Manually trigger or retry selector self-healing for a publication",
    "purge-cache": "Purge eligible raw HTML cache rows according to retention policy",
    "classifier": "Run relevance classifier commands",
    "classifier label": "Run active learning labeling feedback loop",
    "classifier backfill": "Backfill cached relevance metadata and embeddings",
    "classifier train": "Train the classifier using scikit-learn LogisticRegression",
    "classifier reevaluate": "Reevaluate inconclusive/rejected records with the trained model",
}


def add_record_metadata(logger, name, event_dict):
    """
    Extract useful attributes from the standard LogRecord if present.
    This works for both standard logging calls and structlog calls
    processed by ProcessorFormatter.
    """
    record = event_dict.get("_record")
    if record:
        event_dict["logger"] = record.name
        event_dict["filename"] = record.filename
        event_dict["lineno"] = record.lineno
        event_dict["level"] = record.levelname
    return event_dict

class IgnoreStructlogFilter(logging.Filter):
    """
    Filter to ignore log records that originated from structlog,
    preventing duplicate logs in logfire.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, tuple) and len(record.msg) == 2 and isinstance(record.msg[0], dict):
            return False
        return True

def setup_logging(log_file_path: str = ".scratch/pipeline.log", log_level: int = logging.INFO):
    is_testing = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    if is_testing and log_file_path == ".scratch/pipeline.log":
        return

    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    structlog_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.dict_tracebacks,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    has_logfire = False
    try:
        import logfire
        structlog_processors.append(logfire.StructlogProcessor())
        has_logfire = True
    except ImportError:
        pass

    structlog.configure(
        processors=structlog_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    file_handler = RotatingFileHandler(log_file_path, maxBytes=10*1024*1024, backupCount=5)
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.dict_tracebacks,
        ],
        processors=[
            add_record_metadata,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ]
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    if has_logfire:
        logfire_handler = logfire.LogfireLoggingHandler()
        logfire_handler.addFilter(IgnoreStructlogFilter())
        root_logger.addHandler(logfire_handler)

def main(args=None):
    load_dotenv()
    setup_telemetry()
    setup_logging()

    parser = argparse.ArgumentParser(
        description="California Political Influence GraphRAG Engine - Production CLI",
        epilog=(
            "Command paths:\n"
            + "\n".join(
                f"  {command:<30} {description}"
                for command, description in CLI_COMMAND_HELP.items()
            )
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Ingest subcommand
    ingest_parser = subparsers.add_parser("ingest", help=CLI_COMMAND_HELP["ingest"])
    ingest_parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without saving to Neo4j")

    # Clear subcommand
    subparsers.add_parser("clear", help=CLI_COMMAND_HELP["clear"])

    # Analyze subcommand
    subparsers.add_parser("analyze", help=CLI_COMMAND_HELP["analyze"])

    # Janitor subcommand
    subparsers.add_parser("janitor", help=CLI_COMMAND_HELP["janitor"])

    # Register-publication subcommand
    register_parser = subparsers.add_parser("register-publication", help=CLI_COMMAND_HELP["register-publication"])
    register_parser.add_argument("--id", required=True, help="Unique publication identifier (e.g. 'calmatters')")
    register_parser.add_argument("--name", required=True, help="Human-readable publication name (e.g. 'CalMatters')")
    register_parser.add_argument("--base-url", required=True, help="Base URL of the publication (e.g. 'https://calmatters.org')")
    register_parser.add_argument("--crawl-delay", type=float, default=2.0, help="Crawl delay in seconds")
    register_parser.add_argument("--max-concurrency", type=int, default=2, help="Maximum concurrent requests")
    register_parser.add_argument("--use-robots-txt", action="store_true", default=True, help="Respect robots.txt (default)")
    register_parser.add_argument("--no-robots-txt", action="store_false", dest="use_robots_txt", help="Do not respect robots.txt")
    register_parser.add_argument("--discovery-config-json", help="JSON string of discovery configuration parameters")
    register_parser.add_argument("--archive-cutoff-years", type=int, default=5, help="Number of years of historical archive to crawl")
    register_parser.add_argument("--categories", nargs="+", help="Space-separated list of valid categories for the publication")

    # Update-publication subcommand
    update_pub_parser = subparsers.add_parser("update-publication", help=CLI_COMMAND_HELP["update-publication"])
    update_pub_parser.add_argument("--id", required=True, help="Unique publication identifier (e.g. 'calmatters')")
    update_pub_parser.add_argument("--name", help="Human-readable publication name")
    update_pub_parser.add_argument("--base-url", help="Base URL of the publication")
    update_pub_parser.add_argument("--crawl-delay", type=float, help="Crawl delay in seconds")
    update_pub_parser.add_argument("--max-concurrency", type=int, help="Maximum concurrent requests")
    update_pub_parser.add_argument("--use-robots-txt", action="store_true", default=None, help="Respect robots.txt")
    update_pub_parser.add_argument("--no-robots-txt", action="store_false", dest="use_robots_txt", help="Do not respect robots.txt")
    update_pub_parser.add_argument("--discovery-config-json", help="JSON string of discovery configuration parameters")
    update_pub_parser.add_argument("--archive-cutoff-years", type=int, help="Number of years of historical archive to crawl")
    update_pub_parser.add_argument("--categories", nargs="*", help="Space-separated list of valid categories (pass empty to clear)")

    # Update-sources subcommand
    subparsers.add_parser("update-sources", help=CLI_COMMAND_HELP["update-sources"])

    # Scrape-archive subcommand
    archive_parser = subparsers.add_parser("scrape-archive", help=CLI_COMMAND_HELP["scrape-archive"])
    archive_parser.add_argument("--publication-id", required=True, help="ID of the publication to crawl")

    # Refetch-html subcommand
    subparsers.add_parser("refetch-html", help=CLI_COMMAND_HELP["refetch-html"])

    # Validate-articles subcommand
    subparsers.add_parser("validate-articles", help=CLI_COMMAND_HELP["validate-articles"])

    # Review-selectors subcommand
    review_parser = subparsers.add_parser("review-selectors", help=CLI_COMMAND_HELP["review-selectors"])
    review_parser.add_argument("--manual", help="Path to JSON file containing manual selectors to promote")

    # Heal-selectors subcommand
    heal_selectors_parser = subparsers.add_parser("heal-selectors", help=CLI_COMMAND_HELP["heal-selectors"])
    heal_selectors_parser.add_argument("--publication", required=True, help="ID of the publication to heal")
    heal_selectors_parser.add_argument("--retry", action="store_true", help="Mark previous proposal rejected and retry healing with negative context")
    heal_selectors_parser.add_argument("--context", help="Developer-supplied guidance/hint to append to the Generator prompt")

    # Purge-cache subcommand
    subparsers.add_parser("purge-cache", help=CLI_COMMAND_HELP["purge-cache"])

    # Classifier subcommand
    classifier_parser = subparsers.add_parser("classifier", help=CLI_COMMAND_HELP["classifier"])
    classifier_sub = classifier_parser.add_subparsers(dest="classifier_action", required=True)
    label_parser = classifier_sub.add_parser("label", help=CLI_COMMAND_HELP["classifier label"])
    label_parser.add_argument("--review-all", action="store_true", help="Query all cached articles with relevance_label_source != 'HUMAN'")
    classifier_sub.add_parser("backfill", help=CLI_COMMAND_HELP["classifier backfill"])
    classifier_sub.add_parser("train", help=CLI_COMMAND_HELP["classifier train"])
    classifier_sub.add_parser("reevaluate", help=CLI_COMMAND_HELP["classifier reevaluate"])

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
                db_path=db_path,
                categories=parsed_args.categories
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

    elif parsed_args.action == "update-publication":
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
            update_publication(
                pub_id=parsed_args.id,
                name=parsed_args.name,
                base_url=parsed_args.base_url,
                crawl_delay=parsed_args.crawl_delay,
                max_concurrency=parsed_args.max_concurrency,
                use_robots_txt=parsed_args.use_robots_txt,
                discovery_config_json=discovery_config,
                archive_cutoff_years=parsed_args.archive_cutoff_years,
                db_path=db_path,
                categories=parsed_args.categories
            )
            print(f"Successfully updated publication '{parsed_args.id}'.")
            sys.exit(0)
        except ValueError as e:
            # Handle non-existent ID or validation errors cleanly
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
        
        # Run validation on any pending articles
        from knowledge_map.core.validation import ArticleValidatorService
        val_service = ArticleValidatorService(db_path=db_path)
        print("Running validation on pending articles...")
        val_results = asyncio.run(val_service.validate_pending_articles())
        validated_count = sum(1 for r in val_results if r["status"] == "VALIDATED")
        print(f"Validation complete: {validated_count} articles validated successfully.")
        sys.exit(0)

    elif parsed_args.action == "scrape-archive":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        # Ensure database is initialized
        from knowledge_map.adapters.sqlite_db import init_db, get_publication
        init_db(db_path)
        
        pub = get_publication(parsed_args.publication_id, db_path=db_path)
        if not pub:
            print(f"Error: Publication '{parsed_args.publication_id}' not found.", file=sys.stderr)
            sys.exit(1)
            
        service = ArchiveDiscoveryService(db_path=db_path)
        print(f"Starting archive crawl for publication '{parsed_args.publication_id}'...")
        results = asyncio.run(service.run_archive_crawl(pub))
        if results:
            print(f"Scraped {len(results)} new articles during archive crawl:")
            for url in results:
                print(f"  - {url}")
        else:
            print("No new articles scraped during archive crawl.")
            
        # Run validation on any pending articles
        from knowledge_map.core.validation import ArticleValidatorService
        val_service = ArticleValidatorService(db_path=db_path)
        print("Running validation on pending articles...")
        val_results = asyncio.run(val_service.validate_pending_articles())
        validated_count = sum(1 for r in val_results if r["status"] == "VALIDATED")
        print(f"Validation complete: {validated_count} articles validated successfully.")
        sys.exit(0)

    elif parsed_args.action == "refetch-html":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)

        from knowledge_map.core.html_refetch import HtmlRefetchService
        service = HtmlRefetchService(db_path=db_path)
        print("Restoring raw HTML for relevant articles...")
        refetched_urls = asyncio.run(service.refetch_relevant_articles())
        print(f"Refetch complete: {len(refetched_urls)} articles refetched.")
        sys.exit(0)

    elif parsed_args.action == "validate-articles":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        # Ensure database is initialized
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)
        
        from knowledge_map.core.html_refetch import HtmlRefetchService
        refetch_service = HtmlRefetchService(db_path=db_path)
        print("Restoring raw HTML for relevant articles...")
        refetched_urls = asyncio.run(refetch_service.refetch_relevant_articles())
        print(f"Refetch complete: {len(refetched_urls)} articles refetched.")

        from knowledge_map.core.validation import ArticleValidatorService
        service = ArticleValidatorService(db_path=db_path)
        print("Running validation on pending articles...")
        results = asyncio.run(service.validate_pending_articles())
        validated_count = sum(1 for r in results if r["status"] == "VALIDATED")
        failed_count = sum(1 for r in results if r["status"] == "VALIDATION_FAILED")
        unval_count = sum(1 for r in results if r["status"] == "UNVALIDATABLE")
        print(f"Validation complete: {validated_count} validated, {failed_count} validation failed, {unval_count} unvalidatable.")
        sys.exit(0)

    elif parsed_args.action == "review-selectors":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)

        from knowledge_map.core.validation import run_recovery_check, extract_fields
        from knowledge_map.adapters.sqlite_db import (
            get_unresolved_proposals,
            resolve_selector_proposal
        )
        from knowledge_map.core.selectors import add_selector_version, parse_db_datetime
        from knowledge_map.schemas.selectors import ArticleSelectors

        if parsed_args.manual:
            # Manual Promotion Flow
            manual_path = parsed_args.manual
            if not os.path.exists(manual_path):
                print(f"Error: Manual selectors file '{manual_path}' not found.", file=sys.stderr)
                sys.exit(1)

            try:
                with open(manual_path, "r") as f:
                    config = json.load(f)
            except Exception as e:
                print(f"Error: Failed to parse JSON file '{manual_path}': {e}", file=sys.stderr)
                sys.exit(1)

            url = config.get("url")
            selectors_dict = config.get("selectors")
            if not url or not selectors_dict:
                print("Error: JSON must contain 'url' and 'selectors' keys.", file=sys.stderr)
                sys.exit(1)

            # Query raw_html and scraped_at and publication_id from scraped_html_cache
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT publication_id, raw_html, scraped_at
                    FROM scraped_html_cache
                    WHERE url = ?
                """, (url,))
                row = cursor.fetchone()
            finally:
                conn.close()

            if not row:
                print(f"Error: Article '{url}' not found in scraped HTML cache. It must name a validation-failed article.", file=sys.stderr)
                sys.exit(1)

            publication_id = config.get("publication_id") or row["publication_id"]
            scraped_at_str = row["scraped_at"]
            scraped_at = parse_db_datetime(scraped_at_str)

            try:
                selectors = ArticleSelectors(**selectors_dict)
            except Exception as e:
                print(f"Error: Selectors format is invalid: {e}", file=sys.stderr)
                sys.exit(1)

            print(f"Promoting manual selectors for publication '{publication_id}' against recovery article '{url}'...")
            add_selector_version(publication_id, selectors, scraped_at, scraped_at, db_path=db_path)

            success = run_recovery_check(publication_id, url, db_path=db_path)
            if success:
                print(f"Recovery Check passed! Validation for publication '{publication_id}' is now ACTIVE.")
                sys.exit(0)
            else:
                print(f"Recovery Check failed! Validation for publication '{publication_id}' remains PAUSED.", file=sys.stderr)
                sys.exit(1)

        else:
            # Interactive Review Flow
            proposals = get_unresolved_proposals(db_path=db_path)
            if not proposals:
                print("No unresolved selector proposals found.")
                sys.exit(0)

            print(f"Found {len(proposals)} unresolved selector proposal(s):")
            for proposal in proposals:
                prop_id = proposal["id"]
                pub_id = proposal["publication_id"]
                url = proposal["trigger_article_url"]
                status = proposal["status"]
                iterations = proposal["critic_iterations"]
                selectors_data = json.loads(proposal["selectors_json"])

                print("\n" + "="*60)
                print(f"Proposal ID: {prop_id} (Status: {status}, Critic Iterations: {iterations})")
                print(f"Publication: {pub_id}")
                print(f"Triggering Article: {url}")
                print("-" * 60)
                print(f"Proposed Selectors:")
                for k, v in selectors_data.items():
                    print(f"  {k}: {v}")
                print("-" * 60)

                # Fetch raw html to extract preview
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT raw_html, scraped_at FROM scraped_html_cache WHERE url = ?", (url,))
                    cache_row = cursor.fetchone()
                finally:
                    conn.close()

                if cache_row and cache_row["raw_html"]:
                    try:
                        selectors = ArticleSelectors(**selectors_data)
                        extracted = extract_fields(cache_row["raw_html"], selectors)
                        print("Extraction Preview:")
                        print(f"  Title: '{extracted.get('title')}'")
                        print(f"  Author: '{extracted.get('author')}'")
                        print(f"  Date: '{extracted.get('date')}'")
                        body = extracted.get('body', '')
                        print(f"  Body: '{body}'")
                    except Exception as e:
                        print(f"Warning: Failed to preview extraction: {e}")
                else:
                    print("Warning: Raw HTML for the triggering article was not found in cache. Cannot preview.")

                print("-" * 60)
                while True:
                    ans = input("Approve this proposal? (y/yes, n/no, s/skip): ").strip().lower()
                    if ans in ("y", "yes"):
                        resolve_selector_proposal(prop_id, "APPROVED", db_path=db_path)
                        scraped_at = parse_db_datetime(cache_row["scraped_at"]) if cache_row else datetime.datetime.now(datetime.timezone.utc)
                        selectors = ArticleSelectors(**selectors_data)
                        add_selector_version(pub_id, selectors, scraped_at, scraped_at, db_path=db_path)
                        print(f"Proposal {prop_id} APPROVED. Registered new Selector Version.")
                        print("Running Recovery Check...")
                        success = run_recovery_check(pub_id, url, db_path=db_path)
                        if success:
                            print(f"Recovery Check passed! Validation for publication '{pub_id}' is now ACTIVE.")
                        else:
                            print(f"Recovery Check failed! Validation for publication '{pub_id}' remains PAUSED.")
                        break
                    elif ans in ("n", "no"):
                        resolve_selector_proposal(prop_id, "REJECTED", db_path=db_path)
                        print(f"Proposal {prop_id} REJECTED.")
                        break
                    elif ans in ("s", "skip"):
                        print(f"Proposal {prop_id} skipped.")
                        break
                    else:
                        print("Invalid input. Please enter 'y', 'n', or 's'.")

            print("\nAll proposals processed.")
            sys.exit(0)

    elif parsed_args.action == "heal-selectors":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        from knowledge_map.adapters.sqlite_db import (
            init_db,
            get_publication,
            set_publication_healing_in_progress,
            resolve_selector_proposal,
            get_latest_selector_proposal
        )
        init_db(db_path)

        pub_id = parsed_args.publication
        pub = get_publication(pub_id, db_path=db_path)
        if not pub:
            print(f"Error: Publication '{pub_id}' not found.", file=sys.stderr)
            sys.exit(1)

        custom_context = parsed_args.context
        retry_negative_selectors = None
        tripping_article_url = None

        if parsed_args.retry:
            proposal = get_latest_selector_proposal(pub_id, db_path=db_path)
            if not proposal:
                print(f"Error: No selector proposal found to retry for publication '{pub_id}'.", file=sys.stderr)
                sys.exit(1)

            tripping_article_url = proposal["trigger_article_url"]
            retry_negative_selectors = proposal["selectors_json"]

            # Mark the old proposal as REJECTED
            resolve_selector_proposal(proposal["id"], "REJECTED", db_path=db_path)
            print(f"Marking selector proposal {proposal['id']} as REJECTED.")
        else:
            tripping_article_url = pub.get("tripping_article_url")
            if not tripping_article_url:
                # Fall back to latest proposal's tripping article URL if present
                proposal = get_latest_selector_proposal(pub_id, db_path=db_path)
                if proposal:
                    tripping_article_url = proposal["trigger_article_url"]
                else:
                    print(f"Error: Publication '{pub_id}' does not have a tripping article URL.", file=sys.stderr)
                    sys.exit(1)

        print(f"Running selector healing for publication '{pub_id}' on article '{tripping_article_url}'...")
        # Reset healing_in_progress flag first to bypass guards
        set_publication_healing_in_progress(pub_id, False, db_path=db_path)

        from knowledge_map.core.healing import run_selector_healing_flow
        asyncio.run(run_selector_healing_flow(
            publication_id=pub_id,
            tripping_article_url=tripping_article_url,
            db_path=db_path,
            custom_context=custom_context,
            retry_negative_selectors=retry_negative_selectors,
            bypass_guards=True
        ))
        sys.exit(0)

    elif parsed_args.action == "purge-cache":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        from knowledge_map.adapters.sqlite_db import init_db, purge_html_cache
        init_db(db_path)
        
        print("Purging raw HTML cache...")
        counts = purge_html_cache(db_path=db_path)
        print(f"Total rows purged: {counts['total']}.")
        sys.exit(0)

    elif parsed_args.action == "classifier":
        db_path = os.environ.get("SQLITE_DB_PATH", settings.batch_ingestion.db_path)
        from knowledge_map.adapters.sqlite_db import init_db
        init_db(db_path)

        if parsed_args.classifier_action == "backfill":
            from knowledge_map.core.relevance_classification import backfill_relevance_training_data

            result = backfill_relevance_training_data(db_path=db_path)
            print(
                f"Backfilled {result.updated} of {result.candidates} cached articles."
            )
            sys.exit(0)

        elif parsed_args.classifier_action == "label":
            from knowledge_map.adapters.sqlite_db import (
                delete_uningested_story,
                get_articles_for_human_labeling,
                update_article_metadata,
                update_cached_html_status,
            )
            from knowledge_map.core.relevance import deserialize_embedding
            from knowledge_map.core.relevance_classification import (
                get_metadata_embedding,
                persist_relevance_label,
            )

            review_all = getattr(parsed_args, "review_all", False)
            rows = get_articles_for_human_labeling(include_all=review_all, db_path=db_path)

            if not rows:
                if review_all:
                    print("No articles with relevance_label_source != 'HUMAN' found to label.")
                else:
                    print("No non-human INCONCLUSIVE articles found to label.")
                sys.exit(0)
                
            print(f"Found {len(rows)} articles requiring relevance labeling.")
            print("For each article, enter 'y' for RELEVANT, 'n' for IRRELEVANT, 's' to skip, or 'q' to quit.\n")
            
            for url, headline, description, emb_blob in rows:
                print("-" * 60)
                print(f"URL: {url}")
                print(f"Headline: {headline or 'N/A'}")
                print(f"Description: {description or 'N/A'}")
                print("-" * 60)
                
                while True:
                    try:
                        choice = input("Is this California politics? [y/n/s/q]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\nExiting labeling tool.")
                        sys.exit(0)
                    if choice in ('y', 'n'):
                        status = "RELEVANT" if choice == 'y' else "IRRELEVANT"
                        validation = "PENDING" if status == "RELEVANT" else None
                        
                        embedding = deserialize_embedding(emb_blob) if emb_blob else None
                        embedding = get_metadata_embedding(headline, description, embedding)
                        update_article_metadata(
                            url,
                            headline,
                            description,
                            embedding,
                            db_path=db_path,
                        )

                        relevance_update = persist_relevance_label(
                            url,
                            status,
                            "HUMAN",
                            db_path=db_path
                        )
                        if relevance_update.applied:
                            update_cached_html_status(url, validation, db_path=db_path)
                            if status == "IRRELEVANT":
                                delete_uningested_story(url, db_path=db_path)
                        print(
                            f"Labeled: {relevance_update.status} "
                            f"({relevance_update.label_source}) -> validation: {validation}"
                        )
                        break
                    elif choice == 's':
                        print("Skipped.")
                        break
                    elif choice == 'q':
                        print("Exiting labeling tool.")
                        sys.exit(0)
                    else:
                        print("Invalid input. Please enter 'y', 'n', 's', or 'q'.")
            sys.exit(0)

        elif parsed_args.classifier_action == "train":
            try:
                from classifier.trainer import train_classifier
            except ImportError:
                print("Error: ca-political-classifier package is not installed or scikit-learn is missing. Run `uv sync` to install.")
                sys.exit(1)
            
            train_classifier(db_path=db_path)
            sys.exit(0)

        elif parsed_args.classifier_action == "reevaluate":
            from knowledge_map.adapters.sqlite_db import (
                get_machine_labeled_for_reevaluation,
                update_cached_html_status,
                update_relevance_status,
            )
            from knowledge_map.core.relevance import deserialize_embedding, classify_article

            rows = get_machine_labeled_for_reevaluation(db_path=db_path)

            if not rows:
                print("No inconclusive or irrelevant records found to reevaluate.")
                sys.exit(0)
                
            transition_count = 0
            for url, headline, description, emb_blob, old_status in rows:
                embedding = deserialize_embedding(emb_blob)
                if not embedding:
                    continue
                    
                new_status = classify_article(headline, description, embedding)
                if new_status != old_status:
                    if new_status == "RELEVANT":
                        new_validation = "PENDING"
                    else:
                        new_validation = None
                        
                    relevance_update = update_relevance_status(
                        url,
                        new_status,
                        "MODEL",
                        db_path=db_path,
                    )
                    if relevance_update.applied:
                        update_cached_html_status(url, new_validation, db_path=db_path)
                        print(
                            f"URL: {url} transitioned: {old_status} -> "
                            f"{relevance_update.status} (validation: {new_validation})"
                        )
                        transition_count += 1
                    
            print(f"Reevaluation completed. {transition_count} records transitioned to new states.")
            sys.exit(0)

if __name__ == "__main__":
    main()
