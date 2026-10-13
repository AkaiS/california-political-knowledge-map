"""Record source content independently of Git history in the build context."""

import hashlib
import json
import os
from pathlib import Path

root = Path("/app")
files = sorted(path for path in (root / "src").rglob("*") if path.is_file())
content = hashlib.sha256()
for path in files:
    content.update(str(path.relative_to(root)).encode() + b"\0")
    content.update(path.read_bytes())
    content.update(b"\0")
(root / "deployment/build-metadata.json").write_text(
    json.dumps(
        {
            "revision": os.environ.get("BUILD_REVISION", "unknown"),
            "source_sha256": content.hexdigest(),
            "python": "3.13.5",
            "neo4j": "2026.07.1",
            "llama_cpp": "dee2a846b82f15d27f84a48fa387cb53e0d99c25",
        },
        indent=2,
    )
    + "\n"
)
