from knowledge_map.evaluation import CaseMetricObservation, RunMetricObservation


def test_metric_observations_store_only_their_producer_owner():
    assert "case_result_id" not in CaseMetricObservation.model_fields
    assert "run_id" not in CaseMetricObservation.model_fields
    assert "run_id" not in RunMetricObservation.model_fields
    assert "case_result_id" not in RunMetricObservation.model_fields

