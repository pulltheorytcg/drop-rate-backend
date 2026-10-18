"""The recorded default-camera failures must reach book review, not card search."""
import json
from pathlib import Path

import httpx
import pytest

from app.book_observation import book_route
from app.book_recognition import immediate_book_result
from app.recognition_vision import OpenAIRecognitionVisionClient, OBSERVATION_SCHEMA, RecognitionObservation
from test_book_recognition import observed
from test_recognition_vision_transport import observation_payload

RECORDING = json.loads((Path(__file__).parent / 'fixtures/book_auto_route_20261018.json').read_text())


@pytest.mark.parametrize('scan', RECORDING['scans'])
def test_all_eight_recorded_comics_request_book_reader(scan):
    observation = RecognitionObservation.model_validate(scan['observation'])
    assert observation.book is None  # Historical responses, not invented new OCR.
    assert book_route(observation)


@pytest.mark.parametrize('overrides', [
    {}, {'object_type':'UNKNOWN','game':'One Piece'},
    {'object_type':'UNKNOWN','card_number':'OP01-001'},
    {'object_type':'NONE','notes':['This is not a comic book.']},
    {'object_type':'NONE','notes':['No collectible is visible.']},
    {'object_type':'UNKNOWN','object_type_confidence':.4},
])
def test_cards_and_empty_or_uncertain_frames_do_not_become_books(overrides):
    data = {**observation_payload(), 'notes':['The comic book art depicts a manga character.'], **overrides}
    assert not book_route(RecognitionObservation.model_validate(data))


@pytest.mark.asyncio
async def test_one_vision_call_returns_book_identity_and_selected_publisher_cover():
    book = observed(series_title='The Amazing Spider-Man', issue_number='795', language='English', publisher='Marvel')
    book = book.model_copy(update={'category':'MARVEL_COMICS','book_format':'SINGLE_ISSUE'})
    data = {**observation_payload(), 'object_type':'BOOK', 'game':'Unknown', 'card_number':'', 'book':book.model_dump()}
    calls=[]
    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'output_text':json.dumps(data),'usage':{}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        response = await OpenAIRecognitionVisionClient(api_key='fixture',model='fixture',http_client=http).observe_with_telemetry('data:image/jpeg;base64,fixture')
    assert book_route(response.observation) and len(calls)==1
    result = immediate_book_result(response.observation.book, '11111111-1111-4111-8111-111111111111')
    assert result['fields']['issue_number']=='795' and result['fields']['release_year']==2018
    assert result['research']['selected_candidate_id']
    assert result['research']['candidates'][0]['image_path'].startswith('/api/v1/owner/books/research/')
    assert result['auto_save'] is False and result['market_value_minor'] is None
    assert 'printing_number' not in result['fields']


def test_nested_book_schema_is_strict_and_never_requests_condition_or_price():
    for obj in [OBSERVATION_SCHEMA, *OBSERVATION_SCHEMA['$defs'].values()]:
        assert obj['additionalProperties'] is False
        assert set(obj['properties'])==set(obj['required'])
    assert 'BOOK' in OBSERVATION_SCHEMA['properties']['object_type']['enum']
    assert not {'condition','market_value_minor','price'} & OBSERVATION_SCHEMA['$defs']['BookFields']['properties'].keys()
