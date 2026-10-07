"""Explicit prompt versions used by the production Jev execution path."""

from knowledge_map.prompts import load_prompt

JEV_PROMPTS = {
    "jev-staged/predicate-logic": load_prompt("jev-staged/predicate-logic", version=1),
    "jev-staged/predicate-logic-conjunction": load_prompt(
        "jev-staged/predicate-logic-conjunction", version=1
    ),
    "jev-staged/predicate-logic-alternatives": load_prompt(
        "jev-staged/predicate-logic-alternatives", version=1
    ),
    "jev-staged/predicate-logic-unclear": load_prompt(
        "jev-staged/predicate-logic-unclear", version=1
    ),
    "jev-staged/role-occurrences": load_prompt(
        "jev-staged/role-occurrences", version=2
    ),
    "jev-staged/role-occurrences-shared": load_prompt(
        "jev-staged/role-occurrences-shared", version=2
    ),
    "jev-staged/role-occurrences-source-separate": load_prompt(
        "jev-staged/role-occurrences-source-separate", version=1
    ),
    "jev-staged/role-occurrences-target-separate": load_prompt(
        "jev-staged/role-occurrences-target-separate", version=1
    ),
    "jev-staged/role-occurrences-unclear": load_prompt(
        "jev-staged/role-occurrences-unclear", version=2
    ),
    "jev-staged/composer-attachment-correction": load_prompt(
        "jev-staged/composer-attachment-correction", version=1
    ),
    "jev-staged/catalog-pieces-01": load_prompt(
        "jev-staged/catalog-pieces-01", version=1
    ),
    "jev-staged/catalog-pieces-02": load_prompt(
        "jev-staged/catalog-pieces-02", version=1
    ),
    "jev-staged/catalog-pieces-03": load_prompt(
        "jev-staged/catalog-pieces-03", version=1
    ),
    "jev-staged/catalog-pieces-04": load_prompt(
        "jev-staged/catalog-pieces-04", version=1
    ),
    "jev-staged/catalog-pieces-05": load_prompt(
        "jev-staged/catalog-pieces-05", version=1
    ),
    "jev-staged/catalog-pieces-06": load_prompt(
        "jev-staged/catalog-pieces-06", version=1
    ),
    "jev-staged/filtered-fragments-filter-attachment-rules-01": load_prompt(
        "jev-staged/filtered-fragments-filter-attachment-rules-01", version=1
    ),
    "jev-staged/filtered-fragments-filter-attachment-rules-02": load_prompt(
        "jev-staged/filtered-fragments-filter-attachment-rules-02", version=1
    ),
    "jev-staged/filtered-fragments-filter-attachment-rules-03": load_prompt(
        "jev-staged/filtered-fragments-filter-attachment-rules-03", version=1
    ),
    "jev-staged/filtered-fragments-filter-attachment-rules-04": load_prompt(
        "jev-staged/filtered-fragments-filter-attachment-rules-04", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-01": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-01", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-02": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-02", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-03": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-03", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-04": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-04", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-05": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-05", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-06": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-06", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-07": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-07", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-08": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-08", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-09": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-09", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-10": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-10", version=1
    ),
    "jev-staged/filtered-fragments-filter-prompt-11": load_prompt(
        "jev-staged/filtered-fragments-filter-prompt-11", version=1
    ),
    "jev-staged/fragment-selector-aggregate-fragments-01": load_prompt(
        "jev-staged/fragment-selector-aggregate-fragments-01", version=1
    ),
    "jev-staged/fragment-selector-entity-fragments-01": load_prompt(
        "jev-staged/fragment-selector-entity-fragments-01", version=1
    ),
    "jev-staged/fragment-selector-entity-fragments-02": load_prompt(
        "jev-staged/fragment-selector-entity-fragments-02", version=1
    ),
    "jev-staged/fragment-selector-filter-fragments-01": load_prompt(
        "jev-staged/fragment-selector-filter-fragments-01", version=1
    ),
    "jev-staged/fragment-selector-filter-fragments-02": load_prompt(
        "jev-staged/fragment-selector-filter-fragments-02", version=1
    ),
    "jev-staged/fragment-selector-prompt-01": load_prompt(
        "jev-staged/fragment-selector-prompt-01", version=1
    ),
    "jev-staged/fragment-selector-prompt-02": load_prompt(
        "jev-staged/fragment-selector-prompt-02", version=1
    ),
    "jev-staged/fragment-selector-prompt-03": load_prompt(
        "jev-staged/fragment-selector-prompt-03", version=1
    ),
    "jev-staged/fragment-selector-prompt-04": load_prompt(
        "jev-staged/fragment-selector-prompt-04", version=1
    ),
    "jev-staged/fragment-selector-relationship-description-01": load_prompt(
        "jev-staged/fragment-selector-relationship-description-01", version=1
    ),
    "jev-staged/fragment-selector-relationship-description-02": load_prompt(
        "jev-staged/fragment-selector-relationship-description-02", version=2
    ),
    "jev-staged/fragment-selector-relationship-description-03": load_prompt(
        "jev-staged/fragment-selector-relationship-description-03", version=2
    ),
    "jev-staged/jev-schema-filter-build-request-01": load_prompt(
        "jev-staged/jev-schema-filter-build-request-01", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-02": load_prompt(
        "jev-staged/jev-schema-filter-build-request-02", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-03": load_prompt(
        "jev-staged/jev-schema-filter-build-request-03", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-04": load_prompt(
        "jev-staged/jev-schema-filter-build-request-04", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-05": load_prompt(
        "jev-staged/jev-schema-filter-build-request-05", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-06": load_prompt(
        "jev-staged/jev-schema-filter-build-request-06", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-07": load_prompt(
        "jev-staged/jev-schema-filter-build-request-07", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-08": load_prompt(
        "jev-staged/jev-schema-filter-build-request-08", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-09": load_prompt(
        "jev-staged/jev-schema-filter-build-request-09", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-10": load_prompt(
        "jev-staged/jev-schema-filter-build-request-10", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-11": load_prompt(
        "jev-staged/jev-schema-filter-build-request-11", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-12": load_prompt(
        "jev-staged/jev-schema-filter-build-request-12", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-13": load_prompt(
        "jev-staged/jev-schema-filter-build-request-13", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-14": load_prompt(
        "jev-staged/jev-schema-filter-build-request-14", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-15": load_prompt(
        "jev-staged/jev-schema-filter-build-request-15", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-16": load_prompt(
        "jev-staged/jev-schema-filter-build-request-16", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-17": load_prompt(
        "jev-staged/jev-schema-filter-build-request-17", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-18": load_prompt(
        "jev-staged/jev-schema-filter-build-request-18", version=1
    ),
    "jev-staged/jev-schema-filter-build-request-19": load_prompt(
        "jev-staged/jev-schema-filter-build-request-19", version=1
    ),
    "jev-staged/jev-schema-filter-schema-candidates-01": load_prompt(
        "jev-staged/jev-schema-filter-schema-candidates-01", version=1
    ),
    "jev-staged/jev-schema-filter-schema-candidates-02": load_prompt(
        "jev-staged/jev-schema-filter-schema-candidates-02", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-01": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-01", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-02": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-02", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-03": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-03", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-04": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-04", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-05": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-05", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-06": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-06", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-07": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-07", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-08": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-08", version=1
    ),
    "jev-staged/jev-staged-selector-parent-role-prompt-09": load_prompt(
        "jev-staged/jev-staged-selector-parent-role-prompt-09", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-01": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-01", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-02": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-02", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-03": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-03", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-04": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-04", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-05": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-05", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-06": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-06", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-07": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-07", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-08": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-08", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-09": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-09", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-10": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-10", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-11": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-11", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-12": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-12", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-13": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-13", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-14": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-14", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-15": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-15", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-16": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-16", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-17": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-17", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-18": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-18", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-19": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-19", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-20": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-20", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-21": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-21", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-22": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-22", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-23": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-23", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-24": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-24", version=1
    ),
    "jev-staged/jev-staged-selector-select-pieces-25": load_prompt(
        "jev-staged/jev-staged-selector-select-pieces-25", version=1
    ),
    "jev-staged/jev-staged-selector-structural-prompt-01": load_prompt(
        "jev-staged/jev-staged-selector-structural-prompt-01", version=1
    ),
    "jev-staged/jev-staged-selector-structural-prompt-02": load_prompt(
        "jev-staged/jev-staged-selector-structural-prompt-02", version=1
    ),
    "jev-staged/jev-staged-selector-structural-prompt-03": load_prompt(
        "jev-staged/jev-staged-selector-structural-prompt-03", version=1
    ),
    "jev-staged/jev-staged-selector-structural-prompt-04": load_prompt(
        "jev-staged/jev-staged-selector-structural-prompt-04", version=1
    ),
    "jev-staged/jev-staged-selector-structural-prompt-05": load_prompt(
        "jev-staged/jev-staged-selector-structural-prompt-05", version=1
    ),
    "jev-staged/reporting-keyword-gate-gate-criteria-01": load_prompt(
        "jev-staged/reporting-keyword-gate-gate-criteria-01", version=1
    ),
    "jev-staged/reporting-keyword-gate-gate-criteria-02": load_prompt(
        "jev-staged/reporting-keyword-gate-gate-criteria-02", version=1
    ),
    "jev-staged/reporting-keyword-gate-gate-decision-01": load_prompt(
        "jev-staged/reporting-keyword-gate-gate-decision-01", version=1
    ),
    "jev-staged/runner-binder-instructions-01": load_prompt(
        "jev-staged/runner-binder-instructions-01", version=2
    ),
    "jev-staged/runner-binding-prompt-01": load_prompt(
        "jev-staged/runner-binding-prompt-01", version=2
    ),
    "jev-staged/runner-binding-prompt-02": load_prompt(
        "jev-staged/runner-binding-prompt-02", version=1
    ),
    "jev-staged/runner-composer-instructions-01": load_prompt(
        "jev-staged/runner-composer-instructions-01", version=1
    ),
    "jev-staged/runner-composer-prompt-01": load_prompt(
        "jev-staged/runner-composer-prompt-01", version=1
    ),
    "jev-staged/runner-composer-prompt-02": load_prompt(
        "jev-staged/runner-composer-prompt-02", version=1
    ),
    "jev-staged/runner-composer-prompt-03": load_prompt(
        "jev-staged/runner-composer-prompt-03", version=1
    ),
    "jev-staged/runner-composer-prompt-04": load_prompt(
        "jev-staged/runner-composer-prompt-04", version=1
    ),
}
