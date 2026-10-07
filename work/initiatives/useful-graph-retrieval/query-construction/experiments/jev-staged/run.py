"""Run the preserved combined Jev experiment against the development set."""

import os
import sys

from bootstrap import REPOSITORY, activate


def main():
    runtime = activate()
    import keyring
    from dotenv import load_dotenv
    from knowledge_map.prototypes.atomic_deterministic_hydration import (
        jev_staged_selector,
        runner,
    )

    import fragment_selector
    import peer_wording
    import reporting_keyword_gate

    load_dotenv(REPOSITORY / ".env")
    if not os.environ.get("TYPESAFE_API_KEY"):
        api_key = keyring.get_password("jev_api", "test_key")
        if not api_key:
            raise RuntimeError("Set TYPESAFE_API_KEY or configure the Jev Keychain entry")
        os.environ["TYPESAFE_API_KEY"] = api_key
    peer_wording.apply(runner, jev_staged_selector, fragment_selector)
    reporting_keyword_gate.apply(runner, jev_staged_selector, fragment_selector)
    sys.argv[1:1] = [
        "--selector", "jev-staged", "--schema-filter", "jev",
        "--schema-threshold", ".8",
        "--output", str(runtime / "results/report.json"),
        "--raw-events", str(runtime / "results/events.jsonl"),
    ]
    runner.main()


if __name__ == "__main__":
    main()
