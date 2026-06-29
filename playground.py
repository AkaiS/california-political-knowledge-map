import argparse
import os
import sys
import re
import math
from dotenv import load_dotenv
from extraction import extract_entities
from schemas import ExtractionResult
from db import get_last_n_stories, get_all_stories
from coreference import resolve_coreferences, replace_tags_with_entities
from chunking import chunk_article
import asyncio
from config import settings

from graph_db import Neo4jAdapter, Neo4jConfigError, Neo4jConnectionError
from embedding import get_embedding_embedder, cosine_similarity

# Alias for backward compatibility
Neo4jManager = Neo4jAdapter


def process_story(
    manager: Neo4jAdapter | None,
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
        expected_dim = settings.embedding.dimension
        if embeddings and len(embeddings[0]) != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch. The embedding model returned vectors of size "
                f"{len(embeddings[0])}, but Neo4j index is configured for size {expected_dim}. "
                f"Please update EMBEDDING_DIMENSION in your .env file to match the model's native output."
            )
    else:
        embeddings = []

    if not dry_run:
        if not manager:
            raise Neo4jConfigError("Neo4jAdapter not provided for non-dry-run mode.")
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
                manager = Neo4jAdapter(uri=uri, username=username, password=password)
                
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
