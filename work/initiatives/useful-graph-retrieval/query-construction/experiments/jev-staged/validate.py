"""Validate both changes together without API, local-model, or graph calls."""

from bootstrap import activate


def main():
    activate()
    from knowledge_map.prototypes.atomic_deterministic_hydration import (
        jev_staged_selector,
        runner,
    )

    import fragment_selector
    import peer_wording
    import reporting_keyword_gate
    import reporting_keyword_gate_validation

    peer = peer_wording.apply(runner, jev_staged_selector, fragment_selector)
    assert peer["changed_description_counts"] == {"peer_source": 37, "peer_target": 37}
    gate = reporting_keyword_gate.apply(runner, jev_staged_selector, fragment_selector)
    assert gate["baseline_thresholds"] == [.52, .8, .52]
    assert runner._relationship_free_mode("unclassified synthetic question") == "forbidden"
    reporting_keyword_gate_validation.main()
    print("Combined variant validated; candidate shapes and thresholds preserved")


if __name__ == "__main__":
    main()
