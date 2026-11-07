from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from app import marketing_run_attention as subject


@pytest.fixture
def record():
    return {'id': uuid4(), 'job_id': uuid4(), 'created_by': uuid4(),
            'revision': 1, 'stage': 'research', 'state': 'FAILED',
            'output': {'error_code': 'untrusted-private-value'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['FAILED', 'UNKNOWN', 'NEEDS_REVIEW'])
async def test_fixed_owner_scoped_alert(monkeypatch, record, state):
    record['state'] = state
    owner, action_id = uuid4(), uuid4()
    record['owner_id'] = uuid4()  # Must not be trusted.
    auth = AsyncMock(return_value={'user_id': record['created_by'], 'owner_id': owner})
    monkeypatch.setattr(subject, 'require_platform_admin', auth)
    connection = AsyncMock()
    connection.fetchrow.return_value = {'id': action_id}
    assert await subject.record_marketing_attention(connection, record) == action_id
    auth.assert_awaited_once_with(connection)
    query, *args = connection.fetchrow.await_args.args
    assert 'on conflict(owner_id,dedupe_key) do nothing' in query.lower()
    assert 'do update' not in query.lower()
    assert args[0] == owner
    assert args[1] == 'MARKETING_' + state
    assert args[2] == ('MEDIUM' if state == 'NEEDS_REVIEW' else 'HIGH')
    assert args[3] == 'marketing-run:' + str(record['id'])
    assert str(record['job_id']) in args[-1]
    assert 'untrusted-private-value' not in str(args)
    assert str(record['owner_id']) not in str(args)
    connection.transaction.assert_not_called()
    connection.commit.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['PREPARED', 'AWAITING_MEDIA', 'RUNNING'])
async def test_non_attention_states_are_not_errors(monkeypatch, record, state):
    record['state'] = state
    auth = AsyncMock()
    monkeypatch.setattr(subject, 'require_platform_admin', auth)
    connection = AsyncMock()
    assert await subject.record_marketing_attention(connection, record) is None
    auth.assert_not_awaited()
    connection.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_actor_is_denied(monkeypatch, record):
    monkeypatch.setattr(subject, 'require_platform_admin', AsyncMock(return_value={
        'user_id': uuid4(), 'owner_id': uuid4()}))
    connection = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await subject.record_marketing_attention(connection, record)
    assert exc.value.status_code == 403
    connection.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_admin_is_denied(monkeypatch, record):
    monkeypatch.setattr(subject, 'require_platform_admin', AsyncMock(side_effect=HTTPException(403, 'Denied')))
    connection = AsyncMock()
    with pytest.raises(HTTPException):
        await subject.record_marketing_attention(connection, record)
    connection.fetchrow.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_is_not_reopened(monkeypatch, record):
    monkeypatch.setattr(subject, 'require_platform_admin', AsyncMock(return_value={
        'user_id': record['created_by'], 'owner_id': uuid4()}))
    connection = AsyncMock()
    connection.fetchrow.return_value = None
    assert await subject.record_marketing_attention(connection, record) is None
    assert 'do nothing' in connection.fetchrow.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_insert_failure_propagates_for_outer_rollback(monkeypatch, record):
    monkeypatch.setattr(subject, 'require_platform_admin', AsyncMock(return_value={
        'user_id': record['created_by'], 'owner_id': uuid4()}))
    connection = AsyncMock()
    connection.fetchrow.side_effect = RuntimeError('fixture insert failure')
    with pytest.raises(RuntimeError, match='fixture insert failure'):
        await subject.record_marketing_attention(connection, record)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [{'stage': 'publishing'}, {'revision': 2}])
async def test_invalid_record_rejected(record, change):
    record.update(change)
    connection = AsyncMock()
    with pytest.raises(ValueError):
        await subject.record_marketing_attention(connection, record)
    connection.fetchrow.assert_not_awaited()
