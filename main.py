import asyncio
import sys


from knowledge_map.utils.telemetry import setup_telemetry


async def main():
    setup_telemetry()
    print("What you want")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting script.")
        sys.exit(0)

