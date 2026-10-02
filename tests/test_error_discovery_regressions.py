"""Protect note drafts, rendered identifiers, and regenerated review evidence."""

import importlib.util
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "prepare_chat_discovery", ROOT / "scripts/prepare_chat_discovery.py"
)
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def run_javascript(code):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for isolated JavaScript regression tests")
    # Execute handlers with small DOM stubs; no browser or network is involved.
    script = (
        (ROOT / "scripts/error_discovery_chat.html")
        .read_text()
        .split("<script>", 1)[1]
        .split("</script>", 1)[0]
        .split("(async()=>", 1)[0]
    )
    stub = """
const elements = new Map();
function element() { return {value:'', style:{}, dataset:{}, innerHTML:'',
    querySelectorAll(){return []}, querySelector(){return null},
    addEventListener(){}, focus(){}, replaceChildren(...children){this.children=children},
    classList:{contains(){return false},toggle(){}}}; }
const document={getElementById(id){if(!elements.has(id))elements.set(id,element());
    return elements.get(id)},querySelectorAll(){return []},addEventListener(){},
    createElement:element};
const window={addEventListener(){}};
const requestAnimationFrame=()=>{};
"""
    result = subprocess.run(
        [node, "-"],
        input=stub + script + code,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_cancel_discards_draft_and_save_queues_only_committed_note():
    result = run_javascript("""
const writes=[];
enqueue=(path,body)=>writes.push({path,body});
renderHighlights=()=>{}; renderList=()=>{};
const item={id:'note-1',note:'Original'}; annotations=[item];
const host=element(); noteAction(item,'edit',host);
host.children[0].value='Discard this'; host.children[0].oninput();
const beforeCancel={note:annotations[0].note,writes:writes.length};
host.children[2].onclick();
const cancelled={note:annotations[0].note,writes:writes.length};
noteAction(annotations[0],'edit',host);
host.children[0].value='  Saved revision  '; host.children[0].oninput();
host.children[1].onclick();
const saved={note:annotations[0].note,writes:[...writes]};
noteAction(annotations[0],'edit',host);
host.children[0].value='  ';host.children[0].oninput();host.children[1].onclick();
console.log(JSON.stringify({beforeCancel,cancelled,saved,
    empty:{note:annotations[0].note,writes:writes.length,disabled:host.children[1].disabled}}));
""")
    assert result["beforeCancel"] == {"note": "Original", "writes": 0}
    assert result["cancelled"] == {"note": "Original", "writes": 0}
    assert result["saved"] == {
        "note": "Saved revision",
        "writes": [
            {
                "path": "annotations",
                "body": {"annotation": {"id": "note-1", "note": "Saved revision"}},
            }
        ],
    }
    assert result["empty"] == {"note": "Saved revision", "writes": 1, "disabled": True}


class Markup(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_saved_identifiers_remain_values_in_all_rendered_views():
    identifier = 'id" onclick="alert(1)"><img src=x onerror=alert(1)>'
    result = run_javascript(
        """
const id="""
        + json.dumps(identifier)
        + """;
samples=[{id,question:'Question'}];
annotations=[{id,record_id:id,note:'Note'}];
suggestions=[{id,record_id:id,quote:'Quote',note:'Suggestion'}];
patterns=[{name:'Pattern',annotation_ids:[id]}];manifest={case_count:1};
graph={cluster_count:1,points:[{id,x:0,y:0,cluster:0,outcome:'declined'}]};
renderList();renderProgress();renderMap();
console.log(JSON.stringify(Object.fromEntries(['sample-list','patterns','suggestions','map']
    .map(id=>[id,$(id).innerHTML]))));
"""
    )
    for markup in result.values():
        parsed = Markup(markup)
        assert not any(tag in {"img", "script"} for tag, _ in parsed.tags)
        assert not any(
            key.startswith("on") for _, attrs in parsed.tags for key in attrs
        )
    expected = {
        "sample-list": {"data-case"},
        "patterns": {"data-annotation-id", "data-record-id"},
        "suggestions": {"data-suggestion", "data-suggestion-open"},
        "map": {"data-id"},
    }
    for view, attributes in expected.items():
        parsed = Markup(result[view])
        for attribute in attributes:
            assert [
                attrs[attribute] for _, attrs in parsed.tags if attribute in attrs
            ] == [identifier]


@pytest.fixture
def prepared_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    references = {
        "cases": [
            {
                "id": f"case-{i}",
                "feature": "feature",
                "scenario": "scenario",
                "domain_familiarity": "low",
                "evidence_requirement": "One passage",
                "validation": {"basis": "source_text", "evidence_ids": ["chunk-1"]},
            }
            for i in range(24)
        ],
        "evidence": [{"id": "chunk-1", "text": "A 🗳 vote"}],
    }
    report = {
        "model": "test",
        "trace_url": "https://example.test/trace",
        "ran_at": "2026-10-01",
        "report": {
            "cases": [
                {
                    "name": f"case-{i}",
                    "task_duration": i + 1,
                    "metadata": {"reference_artifact": "evidence.json"},
                    "attributes": {},
                    "output": {
                        "question": f"Question {i}",
                        "failure": None,
                        "answer": None,
                        "preparation": {"status": "declined", "message": "Declined"},
                        "rendered_text": None,
                        "retrieval": None,
                        "messages": [],
                        "chat_session_id": f"session-{i}",
                    },
                }
                for i in range(24)
            ]
        },
    }
    telemetry = {
        "results": {
            "operational_details": {
                "rows": [
                    {
                        "attributes": {
                            "chat_session_id": "session-0",
                            "detail": "Original",
                        },
                        "parent_span_id": None,
                    }
                ]
            }
        }
    }
    for name, value in [
        ("report", report),
        ("evidence", references),
        ("telemetry", telemetry),
    ]:
        prepare.save(tmp_path / f"{name}.json", value)
    data_dir = tmp_path / "review"
    prepare.prepare(tmp_path / "report.json", data_dir, tmp_path / "telemetry.json")
    record = json.loads((data_dir / "records.json").read_text())[0]
    block = next(
        b for b in record["blocks"] if b["label"] == "Reference Article Chunk · chunk-1"
    )
    anchor = {
        "id": "note-1",
        "record_id": record["id"],
        "block_id": block["id"],
        "start": 2,
        "end": 4,
        "quote": "🗳",
        "note": "Observation",
    }
    prepare.save(data_dir / "annotations.json", [anchor])
    prepare.save(
        data_dir / "suggestions.json",
        [{**anchor, "id": "suggestion-1", "status": "accepted"}],
    )
    return tmp_path, data_dir


def snapshot(data_dir):
    return {
        path.name: path.read_bytes() for path in data_dir.iterdir() if path.is_file()
    }


def test_unchanged_inputs_preserve_review_and_anchors(prepared_workspace):
    root, data_dir = prepared_workspace
    before = snapshot(data_dir)
    prepare.prepare(root / "report.json", data_dir, root / "telemetry.json")
    assert snapshot(data_dir) == before


@pytest.mark.parametrize("input_name", ["evidence", "telemetry"])
@pytest.mark.parametrize("legacy", [False, True])
def test_changed_inputs_cannot_overwrite_existing_review(
    prepared_workspace, input_name, legacy
):
    root, data_dir = prepared_workspace
    if legacy:
        manifest = json.loads((data_dir / "manifest.json").read_text())
        del manifest["reference_sha256"], manifest["telemetry_sha256"]
        prepare.save(data_dir / "manifest.json", manifest)
    value = json.loads((root / f"{input_name}.json").read_text())
    if input_name == "evidence":
        # The quote and offsets still match, but its surrounding evidence changed.
        value["evidence"][0]["text"] += " Changed context"
    else:
        value["results"]["operational_details"]["rows"][0]["attributes"]["detail"] = (
            "Changed"
        )
        records = json.loads((data_dir / "records.json").read_text())
        block = next(
            b for b in records[0]["blocks"] if b["label"].startswith("Live Logfire")
        )
        prepare.save(
            data_dir / "annotations.json",
            [
                {
                    "id": "telemetry-note",
                    "record_id": "case-0",
                    "block_id": block["id"],
                    "start": 0,
                    "end": len(block["anchor_text"].encode("utf-16-le")) // 2,
                    "quote": block["anchor_text"],
                    "note": "Telemetry observation",
                }
            ],
        )
    prepare.save(root / f"{input_name}.json", value)
    before = snapshot(data_dir)
    with pytest.raises(
        ValueError, match="different reference evidence|Evidence changed"
    ):
        prepare.prepare(root / "report.json", data_dir, root / "telemetry.json")
    assert snapshot(data_dir) == before


def test_legacy_workspace_without_cache_still_rejects_broken_anchor(prepared_workspace):
    root, data_dir = prepared_workspace
    manifest = json.loads((data_dir / "manifest.json").read_text())
    del manifest["reference_sha256"], manifest["telemetry_sha256"]
    prepare.save(data_dir / "manifest.json", manifest)
    (data_dir / "records.json").unlink()
    evidence = json.loads((root / "evidence.json").read_text())
    evidence["evidence"][0]["text"] = "Different passage"
    prepare.save(root / "evidence.json", evidence)
    before = snapshot(data_dir)
    with pytest.raises(ValueError, match="Evidence changed"):
        prepare.prepare(root / "report.json", data_dir, root / "telemetry.json")
    assert snapshot(data_dir) == before
