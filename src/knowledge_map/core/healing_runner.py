import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables (such as LOGFIRE_TOKEN)
load_dotenv()

from knowledge_map.cli.main import setup_logging
from knowledge_map.utils.telemetry import setup_telemetry
from knowledge_map.core.healing import run_selector_healing_flow

def main():
    if len(sys.argv) < 4:
        print(
            "Usage: python -m knowledge_map.core.healing_runner <publication_id> <tripping_article_url> <db_path>",
            file=sys.stderr
        )
        sys.exit(1)
        
    publication_id = sys.argv[1]
    tripping_article_url = sys.argv[2]
    db_path = sys.argv[3]
    
    # Configure logging and telemetry
    setup_logging()
    setup_telemetry()
    
    # Run the selector healing flow
    asyncio.run(run_selector_healing_flow(
        publication_id=publication_id,
        tripping_article_url=tripping_article_url,
        db_path=db_path
    ))

if __name__ == "__main__":
    main()
