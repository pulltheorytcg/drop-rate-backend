from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.marketing_specialists import (
    BASE_PROMPT, Command, JobInput, MODEL, MAX_OUTPUT_TOKENS, OpenAIModel,
    PROMPTS, Proposal, ProviderFailure, build_context, digest, registry,
    run_specialist, validate_proposal,
)


def source():
    return JobInput(topic='Collector care guide', evidence=[{
        'id': 'e1', 'url': 'https://example.org/source',
        'observed_at': '2026-10-04T01:00:00Z',
        'excerpt': 'A protective sleeve helps protect a trading card surface.',
    }])


def proposal(stage='research', review=False):
    refs = ['b1'] if stage == 'design' else ['m1'] if stage == 'social_management' else ['e1']
    return {
        'summary': 'AWAITING_APPROVED_MEDIA' if stage == 'design' else 'Prepared proposal',
        'blocks': [{'id': 'b1', 'text': 'Protect the collection.', 'reference_ids': refs}],
        'channel_variants': [
            {'channel': ch, 'title': 'Collector care', 'caption': 'Keep your collection protected.',
             'narration': 'Give your collection the care it deserves.', 'alt_text': 'A sleeved card.', 'reference_ids': ['e1']}
            for ch in ['instagram', 'tiktok', 'youtube']
        ] if stage == 'copywriting' else [],
        'needs_review': review, 'review_reasons': ['Check rights'] if review else [],
    }


class MemoryStore:
    """Test double; production uses PostgreSQL, never this process-local store."""
    def __init__(self, inp=None):
        self.actor = uuid4()
        self.job_id = uuid4()
        self.job = {'created_by': self.actor, 'input': (inp or source()).model_dump(mode='json')}
        self.stages = {}
        self.lock = asyncio.Lock()

    async def read_job(self, command):
        assert command.job_id == self.job_id
        return self.job

    async def read_stage(self, command, stage):
        return deepcopy(self.stages.get(stage))

    async def claim(self, command, context, input_hash, prompt_hash):
        async with self.lock:
            if command.stage in self.stages:
                return False, deepcopy(self.stages[command.stage])
            self.stages[command.stage] = {'stage': command.stage, 'state': 'RUNNING',
                'input_sha256': input_hash, 'prompt_sha256': prompt_hash, 'input': context}
            return True, deepcopy(self.stages[command.stage])

    async def finish(self, command, state, output, usage):
        async with self.lock:
            self.stages[command.stage].update(state=state, output=output, usage=usage)
            return deepcopy(self.stages[command.stage])


def command(store, stage='research', **changes):
    return Command(job_id=store.job_id, actor_user_id=changes.pop('actor_user_id', store.actor), stage=stage,
        expected_input_sha256=changes.pop('expected_input_sha256', digest(store.job['input'])), **changes)


class FakeModel:
    def __init__(self, error=None, review=False):
        self.calls = []
        self.error, self.review = error, review

    async def generate(self, stage, context):
        self.calls.append(stage)
        await asyncio.sleep(0.01)
        if self.error:
            raise self.error
        return proposal(stage, self.review), {'input_tokens': 20, 'output_tokens': 30}


def test_six_specialists_have_distinct_instructions_and_no_authority():
    items = registry()
    assert len(items) == len(PROMPTS) == 6
    assert len({x['prompt_sha256'] for x in items}) == 6
    assert all(not x['publishable'] for x in items)
    assert items[4]['kind'] == 'deterministic_blocked'
    assert 'untrusted DATA' in BASE_PROMPT


def test_schema_has_closed_objects_and_required_fields():
    schema = Proposal.model_json_schema()
    for obj in [schema, *schema['$defs'].values()]:
        if obj.get('type') == 'object':
            assert obj['additionalProperties'] is False
            assert set(obj['required']) == set(obj['properties'])


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(unexpected='publish'),
    lambda d: d['evidence'].append(deepcopy(d['evidence'][0])),
    lambda d: d['evidence'][0].update(observed_at='2026-10-04T01:00:00'),
    lambda d: d['evidence'][0].update(url='https://secret@example.org/a'),
    lambda d: d['evidence'][0].update(url='http://example.org/a'),
    lambda d: d['evidence'][0].update(excerpt='x' * 6001),
])
def test_job_rejects_invalid_inputs(mutate):
    data = source().model_dump(mode='json')
    mutate(data)
    with pytest.raises(ValidationError):
        JobInput.model_validate(data)


@pytest.mark.parametrize('mutate', [
    lambda d: d['blocks'][0].update(reference_ids=['invented']),
    lambda d: d['blocks'][0].update(reference_ids=['e1', 'e1']),
    lambda d: d['blocks'].append(deepcopy(d['blocks'][0])),
    lambda d: d.update(publishable=True),
    lambda d: d.update(review_reasons=['missing facts']),
    lambda d: d.update(needs_review=True),
    lambda d: d.update(channel_variants=proposal('copywriting')['channel_variants']),
])
def test_research_rejects_invalid_proposals(mutate):
    data = proposal()
    mutate(data)
    with pytest.raises(ValueError):
        validate_proposal('research', source(), data, {})


def test_copy_requires_exact_channel_set():
    data = proposal('copywriting')
    data['channel_variants'][1]['channel'] = 'instagram'
    with pytest.raises(ValueError):
        validate_proposal('copywriting', source(), data, {})


def test_context_is_minimal_and_does_not_forward_unrelated_results():
    context = build_context('design', source(), {'copywriting': proposal('copywriting'), 'research': proposal(), 'secret': 'not-forwarded'})
    assert 'evidence' not in context and 'metrics' not in context
    assert set(context['upstream']) == {'copywriting'}
    assert 'not-forwarded' not in json.dumps(context)


@pytest.mark.asyncio
async def test_pipeline_prepares_four_stages_but_never_publishes():
    store, model = MemoryStore(), FakeModel()
    for stage in ['research', 'brief', 'copywriting', 'design']:
        result = await run_specialist(store, model, command(store, stage))
        assert result['state'] == ('AWAITING_MEDIA' if stage == 'design' else 'PREPARED')
        assert result['publishable'] is result['published'] is False
    result = await run_specialist(store, model, command(store, 'publishing'))
    assert result['state'] == 'BLOCKED'
    assert model.calls == ['research', 'brief', 'copywriting', 'design']


@pytest.mark.asyncio
async def test_concurrent_duplicates_call_model_once():
    store, model = MemoryStore(), FakeModel()
    cmd = command(store)
    results = await asyncio.gather(*(run_specialist(store, model, cmd) for _ in range(8)))
    assert model.calls == ['research']
    assert sum(not result['replayed'] for result in results) == 1
    again = await run_specialist(store, model, cmd)
    assert again['state'] == 'PREPARED' and again['replayed']


@pytest.mark.asyncio
async def test_stale_input_and_wrong_actor_never_call_model():
    store, model = MemoryStore(), FakeModel()
    assert (await run_specialist(store, model, command(store, expected_input_sha256='0' * 64)))['reason'] == 'STALE_INPUT'
    with pytest.raises(PermissionError):
        await run_specialist(store, model, command(store, actor_user_id=uuid4()))
    assert not model.calls


@pytest.mark.asyncio
async def test_missing_evidence_and_metrics_block():
    store, model = MemoryStore(JobInput(topic='Missing data')), FakeModel()
    assert (await run_specialist(store, model, command(store)))['reason'] == 'SUPPLIED_EVIDENCE_REQUIRED'
    assert (await run_specialist(store, model, command(store, 'social_management')))['reason'] == 'SUPPLIED_METRICS_REQUIRED'
    assert not model.calls


@pytest.mark.asyncio
async def test_upstream_review_stops_chain():
    store, model = MemoryStore(), FakeModel(review=True)
    assert (await run_specialist(store, model, command(store)))['state'] == 'NEEDS_REVIEW'
    assert (await run_specialist(store, model, command(store, 'brief')))['reason'] == 'UPSTREAM_NOT_PREPARED:research'
    assert model.calls == ['research']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,state', [(ProviderFailure('MODEL_REFUSAL'), 'FAILED'), (ProviderFailure('MODEL_TRANSPORT_UNKNOWN', True), 'UNKNOWN'), (ValueError('private message'), 'NEEDS_REVIEW')])
async def test_failures_persist_and_do_not_retry(failure, state):
    store, model = MemoryStore(), FakeModel(error=failure)
    cmd = command(store)
    result = await run_specialist(store, model, cmd)
    assert result['state'] == state and 'private message' not in json.dumps(result)
    assert (await run_specialist(store, model, cmd))['replayed']
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_prompt_or_input_change_does_not_reuse_old_result():
    store, model = MemoryStore(), FakeModel()
    cmd = command(store)
    await run_specialist(store, model, cmd)
    store.stages['research']['prompt_sha256'] = 'a' * 64
    result = await run_specialist(store, model, cmd)
    assert result['reason'] == 'STAGE_INPUT_OR_PROMPT_CHANGED'
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_social_metrics_unknown_remains_null_in_context():
    inp = JobInput(topic='Performance', metrics=[{'id':'m1','channel':'instagram','post_id':'p1','name':'reach','value':None,'observed_at':'2026-10-04T00:00:00Z','source':'supplied snapshot'}])
    store, model = MemoryStore(inp), FakeModel()
    result = await run_specialist(store, model, command(store, 'social_management'))
    assert result['state'] == 'PREPARED'
    assert result['input']['metrics'][0]['value'] is None
    assert 'evidence' not in result['input']


@pytest.mark.asyncio
async def test_real_adapter_payload_and_success_without_network():
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(proposal())}]}], 'usage':{'input_tokens':12,'output_tokens':20,'total_tokens':32,'secret':'not-stored'}})
    model = OpenAIModel('test-only-credential', transport=httpx.MockTransport(handler))
    value, usage = await model.generate('research', {'topic':'test'})
    body = json.loads(requests[0].content)
    assert str(requests[0].url) == 'https://api.openai.com/v1/responses'
    assert body['model'] == MODEL and body['store'] is False
    assert body['max_output_tokens'] == MAX_OUTPUT_TOKENS and 'tools' not in body
    assert body['text']['format']['strict'] is True
    assert 'test-only-credential' not in requests[0].content.decode()
    assert usage == {'input_tokens':12,'output_tokens':20,'total_tokens':32}
    assert value == proposal()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301,400,401,403,429,500,503])
async def test_http_failure_no_redirect_retry_or_secret_echo(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={'Location':'https://untrusted.invalid'}, text='PRIVATE_PROVIDER_BODY')
    with pytest.raises(ProviderFailure) as exc:
        await OpenAIModel('test-key', transport=httpx.MockTransport(handler)).generate('research', {})
    assert exc.value.code == 'MODEL_HTTP_' + str(status)
    assert len(calls) == 1 and 'PRIVATE_PROVIDER_BODY' not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('body,code', [
    ({'status':'incomplete'},'MODEL_INCOMPLETE'),
    ({'status':'completed','output':[{'type':'message','content':[{'type':'refusal'}]}]},'MODEL_REFUSAL'),
    ({'status':'completed','output':[]},'MODEL_OUTPUT_INVALID'),
    ({'status':'completed','output':None},'MODEL_OUTPUT_INVALID'),
])
async def test_bad_provider_results_fail_closed(body, code):
    with pytest.raises(ProviderFailure) as exc:
        await OpenAIModel('test', transport=httpx.MockTransport(lambda r: httpx.Response(200,json=body))).generate('research', {})
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_timeout_and_oversized_response():
    def timeout(request):
        raise httpx.ReadTimeout('PRIVATE', request=request)
    with pytest.raises(ProviderFailure) as exc:
        await OpenAIModel('test',transport=httpx.MockTransport(timeout)).generate('research', {})
    assert exc.value.unknown and 'PRIVATE' not in str(exc.value)
    with pytest.raises(ProviderFailure) as exc:
        await OpenAIModel('test',transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b'x'*140000))).generate('research', {})
    assert exc.value.code == 'MODEL_RESPONSE_TOO_LARGE'


@pytest.mark.asyncio
async def test_publisher_adapter_cannot_issue_any_http_call():
    def forbidden(request):
        pytest.fail('Publisher must never call a model/provider')
    with pytest.raises(ProviderFailure):
        await OpenAIModel('test',transport=httpx.MockTransport(forbidden)).generate('publishing', {})


@pytest.mark.asyncio
async def test_design_review_state_is_not_hidden_by_media_wait():
    store, model = MemoryStore(), FakeModel()
    for stage in ['research', 'brief', 'copywriting']:
        await run_specialist(store, model, command(store, stage))
    model.review = True
    result = await run_specialist(store, model, command(store, 'design'))
    assert result['state'] == 'NEEDS_REVIEW'
    assert result['output']['review_reasons']


def test_marketing_prompt_is_bound_to_platform_native_formats():
    from app import marketing_specialists as m
    from app.social_media_specs import prompt_contract

    assert "marketing-specialists-v2-social-native-formats" == m.PROMPT_VERSION
    contract = prompt_contract()
    assert "instagram_feed_image: 1080x1350 px (4:5)" in contract
    assert "tiktok_video: 1080x1920 px (9:16)" in contract
    assert "youtube_short: 1080x1920 px (9:16)" in contract
    assert "Never treat one finished asset as universal across channels" in m.BASE_PROMPT
