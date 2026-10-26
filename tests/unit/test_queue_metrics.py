from app.observability.queue_metrics import render_queue_metrics


def test_metrics_include_zero_states_and_only_aggregates() -> None:
    payload = render_queue_metrics({"queued": 2, "failed": 1}, 12.5, 1.2, True, 3)
    assert 'rag_document_jobs{status="queued"} 2' in payload
    assert 'rag_document_jobs{status="succeeded"} 0' in payload
    assert "rag_document_worker_heartbeat 1" in payload
    assert "rag_celery_broker_messages 3" in payload
    assert "document_id" not in payload and "filename" not in payload
    assert "tenant" not in payload and "prompt" not in payload
