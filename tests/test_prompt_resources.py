"""Protect migrated prompt bytes, runtime rendering, and explicit resource versions."""

import ast
import hashlib
import json
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rendered_prompt_snapshot():
    from knowledge_map.adapters import coreference, policy_areas, stance_alignment
    from knowledge_map.adapters.extraction import load_instructions
    from knowledge_map.adapters.structural import STRUCTURAL_INSTRUCTIONS
    from knowledge_map.core import healing
    from knowledge_map.core.chat import CHAT_INSTRUCTIONS, QUESTION_POLICY
    from knowledge_map.core.question_preparation import QUERY_REWRITER_INSTRUCTIONS
    from knowledge_map.core.relevance_agent import (
        RELEVANCE_AGENT_INSTRUCTIONS,
        get_relevance_agent_prompt,
    )
    from knowledge_map.ontology.extraction_prompt import render_extraction_ontology
    from knowledge_map.schemas import (
        CriticVerdict,
        MentionSpan,
        MentionSpanDiscard,
        Node,
        Relationship,
        SourceArticle,
        StanceAlignmentVerdict,
    )
    from knowledge_map.schemas.structural import PieceSelection

    span = MentionSpan(
        sentence_label="1",
        mention_text="He",
        occurrence=1,
        canonical_entity_name="Gavin {Newsom}",
    )
    spans = [span]
    article = SourceArticle(
        url="https://example.test/a", title="A {title} café", content="He said {this}."
    )
    examples = [{"title": "Example {title}", "content": "Text café\nsecond line"}]
    values = {
        "chat": CHAT_INSTRUCTIONS,
        "question_policy": QUESTION_POLICY,
        "query_rewriter": QUERY_REWRITER_INSTRUCTIONS,
        "coreference_annotator": coreference.ANNOTATOR_INSTRUCTIONS,
        "coreference_critic": coreference.CRITIC_INSTRUCTIONS,
        "coreference_annotation": coreference.ANNOTATION_PROMPT,
        "coreference_numbered": coreference.numbered_article_instructions(
            SimpleNamespace(
                deps=coreference.CoreferenceDeps.for_content(article.content)
            )
        ),
        "coreference_spans": coreference.format_mention_spans(spans),
        "coreference_critic_request": coreference._critic_prompt(spans),
        "coreference_retry": coreference._retry_prompt([(span, "Wrong {entity}")]),
        "coreference_unlocatable": coreference._unlocatable_retry_message(
            [MentionSpanDiscard(mention_span=span, reason="No {location}")]
        ),
        "stance_instructions": stance_alignment.CRITIC_INSTRUCTIONS,
        "stance_request": stance_alignment.critic_prompt(
            article.content,
            [
                Relationship(
                    source="A {source}", target="B", relationship_type="DECLARED_STANCE"
                )
            ],
        ),
        "classification_instructions": policy_areas.CLASSIFICATION_INSTRUCTIONS,
        "assignment_instructions": policy_areas.ASSIGNMENT_INSTRUCTIONS,
        "assignment_request": policy_areas.render_assignment_request(
            article, ["Health"], [Node(name="AB 1", label="Bill")]
        ),
        "relevance_instructions": RELEVANCE_AGENT_INSTRUCTIONS,
        "relevance_no_examples": get_relevance_agent_prompt(
            article.title, article.content, [], []
        ),
        "relevance_positive": get_relevance_agent_prompt(
            article.title, article.content, examples, []
        ),
        "relevance_negative": get_relevance_agent_prompt(
            article.title, article.content, [], examples
        ),
        "relevance_both": get_relevance_agent_prompt(
            article.title, article.content, examples, examples
        ),
        "extraction_instructions": load_instructions(),
        "extraction_ontology": render_extraction_ontology(),
        **STRUCTURAL_INSTRUCTIONS,
    }
    for schema in [
        MentionSpan,
        CriticVerdict,
        Relationship,
        StanceAlignmentVerdict,
        PieceSelection,
    ]:
        values[f"schema_{schema.__name__}"] = json.dumps(
            schema.model_json_schema(), sort_keys=True
        )
    # Evaluate the old/new template expressions with identical data, including
    # braces and non-ASCII text that must survive formatting untouched.
    namespace = {
        **vars(healing),
        "tripping_article_url": "https://example.test/{article}",
        "cleaned_html": "<p>Café {text}</p>",
        "gt": {
            "headline": "A {headline}",
            "datePublished": "2026-09-30",
            "authors": ["A", "B"],
            "wordCount": 150,
        },
        "negative_selectors_str": "negative\n",
        "custom_context_str": "custom\n",
        "retry_negative_selectors": ".old {selector}",
        "custom_context": "Hint {text}",
        "confirmed_selectors": {"title": "h1", "author": None},
        "last_selectors": SimpleNamespace(
            title="h1", author=".author", date="time", body=".content"
        ),
        "extracted": {"title": "A {title}", "author": "Café", "date": "2026-09-30"},
        "ext_body": "Body {text}",
        "ext_word_count": 140,
        "gt_word_count": 150,
        "ratio_str": " (93.3% of expected)",
        "e": ValueError("Bad {selector}"),
        "feedback_messages": ["Error {one}", "Error two"],
    }
    tree = ast.parse(Path(healing.__file__).read_text())
    fields = {
        "instructions",
        "negative_selectors_str",
        "custom_context_str",
        "prompt",
        "locked_selectors_str",
        "ratio_str",
        "critic_input",
    }
    for function in tree.body:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        occurrences = {}
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id in fields
                for target in node.targets
            ):
                if isinstance(node.value, ast.Constant) and node.value.value == "":
                    continue
                value = eval(
                    compile(ast.Expression(node.value), healing.__file__, "eval"),
                    namespace,
                )
                key = next(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
                occurrences[key] = occurrences.get(key, 0) + 1
                values[f"healing_{function.name}_{key}_{occurrences[key]}"] = value
    return {key: _digest(value) for key, value in sorted(values.items())}


def test_resolved_prompt_outputs_match_adopted_versions():
    baseline = json.loads((FIXTURES / "prompt_rendered_baseline.json").read_text())
    baseline.update(
        chat="13a19dad456271de744ef106e41ba64ded60e31dbf15405ae5b6adac61490ac4",
        question_policy="6c6f4d61668b3929c62cff87a6f0030d5d9739c103163c9fee2c97b4dc543ac9",
    )
    assert rendered_prompt_snapshot() == baseline


def test_v1_assets_retain_their_immutable_bytes():
    from knowledge_map.prompts import load_prompt

    baseline = json.loads((FIXTURES / "prompt_v1_baseline.json").read_text())
    assets = files("knowledge_map").joinpath("resources", "prompts")
    actual = {
        str(path.relative_to(Path(str(assets))).parent)
        for path in Path(str(assets)).rglob("v1.txt")
    }
    assert actual == set(baseline)
    for name, expected in baseline.items():
        assert _digest(load_prompt(name, version=1)) == expected["sha256"], name


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (2, "77bc10b279920b877c820c5a373fca009ad90358139ece86820f4f7f788eb5e1"),
        (3, "2233c7624e9941dd4c0a900fd74b698d7b9b3d68f6aa6f03dddb8ac87ae74877"),
        (4, "d17a8772e5cdfa619dcc4bfab7f48edde92bb0214e34f3343df078fb7451792e"),
        (5, "621a9fdc544193f363f8f182636b456e6f5158a0650da75fd7cbfe43ae11ade7"),
        (6, "4fef0ac93fdb5c0d6630334318d073172c4be96f7ccdeaa937144f8b1583fdaa"),
        (7, "27a70c03bd8b7ccb9a16682d8cc7dec9932ade56e569a85a3a461bf2d0277453"),
        (8, "fa0b638eabdd129613e2e7b33ee19a8d1a8ad142da8f7af4be70b7586c6bdb71"),
        (9, "aadc52b6ef9fb05854268247c3b0cf37b713c7e3028f050ae111a46661dfacbc"),
        (10, "c3e7482eefc83784e5d2be283a7f8369b4c29354a84803df7b1dcd10141cbafe"),
        (11, "46446baf8b6dcb45deb1cd60b2b96354bbe55a550c457d4445229bb26e829014"),
        (12, "006a05c2c45fff7b554ab2894cd746fbcc5eb532b260d049b85a80c9592e3a3a"),
        (13, "d204438d9628e272aea0b668ea2bcc0684c626a90941ad2333f0e6f6efdb3fe3"),
        (14, "c9b0001ce2b862b869c4c7046c3688a32d484b08336e0b3e6ac68f891a80f549"),
        (15, "bdde131d657eea35891ca2576ee04b798db74754ddddce292091c006e81a8d7d"),
        (16, "13a19dad456271de744ef106e41ba64ded60e31dbf15405ae5b6adac61490ac4"),
    ],
)
def test_new_chat_instruction_versions_retain_their_immutable_bytes(version, expected):
    from knowledge_map.prompts import load_prompt

    assert _digest(load_prompt("chat/instructions", version=version)) == expected


def test_explicit_version_selection_and_missing_version():
    from knowledge_map.prompts import load_prompt

    assert load_prompt("shared/health-check", version=1) == "health_check"
    with pytest.raises(TypeError):
        load_prompt("shared/health-check")
    with pytest.raises(FileNotFoundError):
        load_prompt("shared/health-check", version=99999)


@pytest.mark.parametrize(
    "name",
    [
        "../secret",
        "/absolute",
        "chat//instructions",
        "chat/latest",
        "Chat/instructions",
    ],
)
def test_invalid_resource_identifiers(name):
    from knowledge_map.prompts import load_prompt

    if name == "chat/latest":
        with pytest.raises(FileNotFoundError):
            load_prompt(name, version=1)
    else:
        with pytest.raises(ValueError):
            load_prompt(name, version=1)


@pytest.mark.parametrize("version", [0, -1, True, "latest", "1"])
def test_invalid_versions(version):
    from knowledge_map.prompts import load_prompt

    with pytest.raises(ValueError):
        load_prompt("chat/instructions", version=version)


def test_modules_pin_versions_and_have_no_inline_agent_instructions():
    paths = [
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.joinpath("classifier", "src").rglob("*.py"),
        *ROOT.joinpath("scripts").glob("*.py"),
        *ROOT.joinpath("work").rglob("*.py"),
    ]
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "load_prompt":
                assert isinstance(node.args[0], ast.Constant), path
                versions = [
                    keyword.value
                    for keyword in node.keywords
                    if keyword.arg == "version"
                ]
                assert (
                    len(versions) == 1
                    and isinstance(versions[0], ast.Constant)
                    and type(versions[0].value) is int
                ), path
            for keyword in node.keywords:
                if keyword.arg in {"instructions", "system_prompt"}:
                    assert not isinstance(
                        keyword.value, (ast.Constant, ast.JoinedStr)
                    ), f"{path}:{keyword.value.lineno} embeds instructions"
