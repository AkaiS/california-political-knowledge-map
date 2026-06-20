import asyncio
import sys


async def main():
    print("What you want")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting script.")
        sys.exit(0)

