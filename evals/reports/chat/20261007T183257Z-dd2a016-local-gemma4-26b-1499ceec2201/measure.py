"""Recompute metrics: uv run python measure.py REPORT REFERENCES OUTPUT."""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean, median


def decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def timings(values):
    return {
        'n': len(values), 'mean': round(fmean(values), 3),
        'p50': round(median(values), 3), 'p95': round(percentile(values, .95), 3),
        'max': round(max(values), 3),
    } if values else {}


path = Path(sys.argv[1])
document = json.loads(path.read_text())
refs = {c['id']: c for c in json.loads(Path(sys.argv[2]).read_text())['cases']}
cases = []
stage_times = defaultdict(list)
branch_statuses = defaultdict(Counter)
usage = Counter()
jev_usage = Counter()
for case in document['report']['cases']:
    output = case['output']
    answer = output.get('answer') or {}
    evidence = answer.get('evidence') or output.get('retrieval') or {}
    outcomes = evidence.get('execution', {}).get('outcomes', [])
    observations = case.get('attributes', {}).get('stage_observations', [])
    assessment = None
    fused = set()
    branch_seconds = {}
    construction_stages = []
    for span in observations:
        attrs = {k: decoded(v) for k, v in span.get('attributes', {}).items()}
        duration = (datetime.fromisoformat(span['finished_at']) - datetime.fromisoformat(span['started_at'])).total_seconds()
        label = span['name']
        if attrs.get('branch'):
            label += ':' + attrs['branch']
            branch_seconds[attrs['branch']] = round(duration, 3)
        elif attrs.get('stage'):
            label += ':' + attrs['stage']
            construction_stages.append({'stage': attrs['stage'], 'status': attrs.get('status'), 'seconds': round(duration, 3), 'error': attrs.get('error')})
        stage_times[label].append(duration)
        if span['name'] == 'chat_session.question_assessment':
            assessment = attrs.get('status')
        if span['name'] == 'chat_session.fusion':
            fused = set(attrs.get('fused_chunk_ids', []))
        if span['name'] == 'chat_session.structural_stage' and attrs.get('stage') in ('schema_filtering', 'typed_selection'):
            jev_usage.update(attrs.get('usage', {}))
    selected = {p['candidate']['chunk_id'] for source in evidence.get('sources', []) for p in source.get('passages', [])}
    branches = {}
    for outcome in outcomes:
        branch = outcome['branch']
        branch_statuses[branch][outcome['status']] += 1
        branches[branch] = {
            'status': outcome['status'], 'seconds': branch_seconds.get(branch),
            'candidate_count': outcome.get('candidate_summary', {}).get('total_retrieved', len(outcome.get('candidates', []))),
            'retained_candidates': len(outcome.get('candidates', [])),
            'semantic_rows': len(outcome.get('semantic_results', [])),
        }
    reference = refs.get(case['name'])
    coverage = None
    if reference:
        rows = reference['rows']
        def covers(row, ids):
            groups = row.get('evidence_groups', [])
            return bool(groups) and all(bool(set(g['ids']) & ids) for g in groups)
        structural = next((o for o in outcomes if o['branch'] == 'structural'), {})
        structural_ids = {x['chunk_id'] for x in structural.get('candidates', [])}
        coverage = {
            'reference_rows': len(rows),
            'jev_supported_rows': sum(covers(r, structural_ids) for r in rows),
            'fused_supported_rows': sum(covers(r, fused) for r in rows),
            'selected_supported_rows': sum(covers(r, selected) for r in rows),
        }
    usage.update(case.get('metrics', {}))
    cases.append({
        'id': case['name'], 'cohort': case['metadata']['cohort'],
        'question': case['inputs']['question'], 'duration': case['task_duration'],
        'failure': output.get('failure'), 'preparation': (output.get('preparation') or {}).get('status'),
        'answer_completed': bool(output.get('answer')) and not output.get('failure'),
        'assessment': assessment, 'branches': branches,
        'reference_evidence_coverage': coverage,
        'sources': len(evidence.get('sources', [])), 'passages': len(selected),
        'context': evidence.get('context'), 'fused_candidates': len(fused),
        'introduction': answer.get('introduction'), 'rendered_text': output.get('rendered_text'),
        'construction_stages': construction_stages,
    })

concrete = [c for c in cases if c['cohort'] == 'populated_graph']
summary = {
    'report': str(path), 'trace_url': document.get('trace_url'),
    'case_count': len(cases), 'cohorts': dict(Counter(c['cohort'] for c in cases)),
    'execution_failures': [c['id'] for c in cases if c['failure']],
    'completed_answers': sum(c['answer_completed'] for c in cases),
    'completed_graph_answers': sum(c['answer_completed'] for c in concrete),
    'partial_or_complete_evidence_packages': sum(c['sources'] > 0 for c in cases),
    'failure_stages': dict(Counter(c['failure']['stage'] for c in cases if c['failure'])),
    'branch_statuses': {k: dict(v) for k, v in branch_statuses.items()},
    'all_case_latency': timings([c['duration'] for c in cases]),
    'concrete_case_latency': timings([c['duration'] for c in concrete]),
    'retrieval_attempt_case_latency': timings([c['duration'] for c in cases if c['branches']]),
    'summed_case_seconds': round(sum(c['duration'] for c in cases), 3),
    'stage_latency': {k: timings(v) for k, v in stage_times.items()},
    'local_model_usage': dict(usage), 'recorded_jev_selector_usage': dict(jev_usage),
    'assessment_by_cohort': {cohort: dict(Counter(c['assessment'] or c['preparation'] for c in cases if c['cohort'] == cohort)) for cohort in {c['cohort'] for c in cases}},
    'control_assessment_target_matches': {
        cohort: {'matches': sum(c['assessment'] == target for c in cases if c['cohort'] == cohort), 'total': sum(c['cohort'] == cohort for c in cases)}
        for cohort, target in (('declined_control', 'declined'), ('deferred_control', 'deferred'))
    },
    'reference_method': 'A reference row is supported when at least one chunk from each authored evidence group is present. Reference queries were rerun against the current graph. These are graph observations, not human answer labels.',
    'reference_evidence': {
        stage: {
            'cases_with_any_supported_row': sum(c['reference_evidence_coverage'][stage + '_supported_rows'] > 0 for c in concrete),
            'cases_with_all_supported_rows': sum(c['reference_evidence_coverage'][stage + '_supported_rows'] == c['reference_evidence_coverage']['reference_rows'] for c in concrete),
            'macro_row_coverage': round(fmean(c['reference_evidence_coverage'][stage + '_supported_rows'] / c['reference_evidence_coverage']['reference_rows'] for c in concrete), 4),
        } for stage in ('jev', 'fused', 'selected')
    },
}
result = {'summary': summary, 'cases': cases}
Path(sys.argv[3]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(summary, indent=2))
print('CASE SUMMARY')
for c in cases:
    print(c['id'], c['assessment'] or c['preparation'], 'failure', bool(c['failure']), 'branches', {k: v['status'] + ':' + str(v['candidate_count']) for k,v in c['branches'].items()}, 'coverage', c['reference_evidence_coverage'])
