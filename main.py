import asyncio
import sys
from db import init_db, save_story, get_last_n_stories
from scraper import fetch_last_5_politics_stories

async def main():
    print("Initializing Database...")
    init_db()
    
    print("\nFetching latest political stories from CalMatters...")
    stories = await fetch_last_5_politics_stories()
    
    if not stories:
        print("No stories fetched. Please check logs.")
        return
        
    print(f"\nFetched {len(stories)} stories. Saving to SQLite database...")
    new_inserts = 0
    duplicates = 0
    
    for story in stories:
        inserted = save_story(story)
        if inserted:
            new_inserts += 1
            print(f"  [NEW] {story['title']}")
        else:
            duplicates += 1
            print(f"  [DUPLICATE] {story['title']}")
            
    print(f"\nSave operation completed: {new_inserts} new stories added, {duplicates} duplicates ignored.")
    
    print("\n--- Current Top 5 Stories in DB ---")
    db_stories = get_last_n_stories(5)
    for idx, s in enumerate(db_stories, 1):
        print(f"\n{idx}. {s['title']}")
        print(f"   URL: {s['url']}")
        print(f"   Category: {s['category']} | Author: {s['author']} | Date: {s['published_date']}")
        print(f"   Summary: {s['summary']}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting script.")
        sys.exit(0)

