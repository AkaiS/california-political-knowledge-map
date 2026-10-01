"""Poll annotation content every two seconds and log changes for the agent."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    previous = None
    while True:
        try:
            content = args.annotations.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != previous:
                notes = json.loads(content)
                print(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "sha256": digest,
                            "note_count": len(notes),
                            "record_ids": sorted({n["record_id"] for n in notes}),
                            "annotation_ids": [n["id"] for n in notes],
                        }
                    ),
                    flush=True,
                )
                previous = digest
        except (OSError, ValueError) as error:
            print(
                json.dumps(
                    {"at": datetime.now(UTC).isoformat(), "error": type(error).__name__}
                ),
                flush=True,
            )
        time.sleep(2)


if __name__ == "__main__":
    main()
