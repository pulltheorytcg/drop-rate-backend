from test_book_connector_import import run_sql
from r2_reference_queue_fixture import SETUP, STEPS, verify


def test_retry_places_new_work_future_backoff_and_changed_source(tmp_path):
    result = run_sql(tmp_path, STEPS, setup=SETUP)
    assert all(row['ok'] for row in result['results']), result
    verify([row['rows'] for row in result['results']])
