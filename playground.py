import argparse
import os
import sys
import re
import math
from dotenv import load_dotenv
from db import get_last_n_stories, get_all_stories
import asyncio
from config import settings

from graph_db import Neo4jAdapter, Neo4jConfigError, Neo4jConnectionError
from embedding import get_embedding_embedder, cosine_similarity

# StoryPipeline and adapters
from schemas import SourceArticle
from embedding import PydanticAIEmbeddingAdapter
from coreference import PydanticAICoreferenceAdapter
from extraction import PydanticAIEntityExtractionAdapter
from pipeline import StoryPipeline

# Alias for backward compatibility
Neo4jManager = Neo4jAdapter

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
        db_adapter = None
        try:
            uri = os.environ.get("NEO4J_URI")
            username = os.environ.get("NEO4J_USERNAME")
            password = os.environ.get("NEO4J_PASSWORD")
            
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
            
            pipeline = StoryPipeline(
                db_adapter=db_adapter,
                embedding_adapter=embedding_adapter,
                coreference_adapter=coreference_adapter,
                extraction_adapter=extraction_adapter
            )
            
            def run_pipeline_story(story_dict: dict, dry_run: bool):
                url = story_dict.get("url") or "http://example.com/text-input"
                title = story_dict.get("title")
                
                article = SourceArticle(
                    url=url,
                    title=title,
                    author=story_dict.get("author"),
                    published_date=story_dict.get("published_date"),
                    content=story_dict.get("content") or ""
                )
                
                if dry_run:
                    print(f"Resolving coreferences for story: {title or url}")
                    print("Chunking story content...")
                    result = pipeline.run(article, dry_run=True)
                    print(f"Split into {len(result.chunks)} chunk(s).")
                    print("Generating vector embeddings...")
                    for idx, chunk in enumerate(result.chunks):
                        chunk_id = f"{article.url}#chunk_{idx}"
                        extraction = result.extractions[idx]
                        print(f"\n--- Chunk {idx} (Dry Run) ---")
                        print(f"Chunk ID: {chunk_id}")
                        print(f"Chunk text snippet: {chunk.text[:120]}...")
                        print("Extracting entities...")
                        print("Validated Extraction Result (JSON):")
                        print(extraction.model_dump_json(indent=2))
                else:
                    print(f"Resolving coreferences for story: {title or url}")
                    print("Chunking story content...")
                    result = pipeline.run(article, dry_run=False)
                    print(f"Split into {len(result.chunks)} chunk(s).")
                    print("Generating vector embeddings...")
                    for idx, chunk in enumerate(result.chunks):
                        print(f"Ingesting Chunk {idx} node into Neo4j...")
                        print(f"Extracting entities from Chunk {idx}...")
                        print(f"Ingesting extraction for Chunk {idx} into Neo4j...")

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
                    run_pipeline_story(story, dry_run=True)
                except Exception as e:
                    print(f"Extraction failed: {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                if parsed_args.text:
                    story = {
                        "content": parsed_args.text,
                        "url": "http://example.com/text-input",
                        "title": "Text Input",
                    }
                    print("Processing provided text through the pipeline...")
                    run_pipeline_story(story, dry_run=False)
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
                            run_pipeline_story(story, dry_run=False)
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
            if db_adapter:
                db_adapter.close()

if __name__ == "__main__":
    main()
