import json

import httpx
import pytest
from pydantic import ValidationError

from app.book_recognition import BookFields, BookObservation, BookScanRequest, BookVisionClient, suggestion, valid_book_barcode
from app.recognition_vision import RecognitionVisionError


def observed(**fields):
    data = {key: dict(value='',visible_text='',confidence=0) for key in BookFields.model_fields}
    for key,value in fields.items():
        data[key] = value if isinstance(value,dict) else dict(value=str(value),visible_text=str(value),confidence=.96)
    return BookObservation(object_type='BOOK',category='MANGA',book_format='MANGA',confidence=.98,fields=data,warnings=[])


@pytest.mark.parametrize('value,valid',[
    ('978-1-56619-909-4',True),('1566199093',True),('080442957X',True),
    ('036000291452',True),('03600029145200111',True),('9781566199095',False),
    ('9781566199094x',False),('123',False),('00000000001',False),
])
def test_checksums(value,valid):
    assert valid_book_barcode(value) is valid


def test_visible_fields_prefill_but_never_save_or_value():
    obs=observed(series_title='One Piece',issue_number=1,publisher='VIZ Media',language='English',
                 release_year=2003,printing_number=1,barcode_gtin='9781566199094',grading_company='BGS',grade='9.5')
    result=suggestion(obs)
    assert result['status']=='NEEDS_REVIEW' and not result['auto_save'] and result['market_value_minor'] is None
    assert result['fields']['printing_number']==1 and result['fields']['grade']=='9.5'
    assert 'condition' not in result['fields'] and 'certificate_number' in result['uncertain_fields']


@pytest.mark.parametrize('field,evidence',[
    ('printing_number',dict(value='1',visible_text='',confidence=.99)),
    ('language',dict(value='English',visible_text='English',confidence=.6)),
    ('barcode_gtin',dict(value='9781566199095',visible_text='9781566199095',confidence=.99)),
    ('release_year',dict(value='1920',visible_text='1920',confidence=.99)),
    ('grade',dict(value='11',visible_text='11',confidence=.99)),
])
def test_uncertain_or_invalid_identity_stays_blank(field,evidence):
    result=suggestion(observed(**{field:evidence}))
    assert field not in result['fields'] and field in result['uncertain_fields']


def test_cards_conflicts_and_unclassified_books_cannot_inherit_defaults():
    for kind in ('NOT_BOOK','UNKNOWN'):
        result=suggestion(observed(series_title='One Piece').model_copy(update={'object_type':kind}))
        assert result['status']=='NO_MATCH' and not result['fields']
    result=suggestion(observed().model_copy(update={'category':'UNKNOWN','book_format':'UNKNOWN'}))
    assert 'system_code' not in result['fields'] and 'language' not in result['fields']
    obs=observed(grading_company='BGS',grade='9.5',certificate_number='123').model_copy(update={'category':'MARVEL_COMICS'})
    assert not {'grading_company','grade','certificate_number'} & suggestion(obs)['fields'].keys()


@pytest.mark.asyncio
async def test_book_transport_keeps_all_photos_and_strict_evidence_schema():
    captured=[]
    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'output_text':observed(series_title='One Piece').model_dump_json(),'usage':{}})
    images=['data:image/jpeg;base64,first','data:image/jpeg;base64,second']
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        result=await BookVisionClient(api_key='fixture',model='fixture-vision',http_client=http).observe_with_telemetry(images)
    assert result.observation.fields.series_title.value=='One Piece'
    body=captured[0]
    assert not body['store'] and body['max_output_tokens']==3000
    assert [x['image_url'] for x in body['input'][0]['content'] if x['type']=='input_image']==images
    schema=body['text']['format']['schema']
    for item in [schema,*schema['$defs'].values()]:
        assert item['additionalProperties'] is False and set(item['required'])==set(item['properties'])
    assert 'market_value_minor' not in json.dumps(schema)


@pytest.mark.asyncio
async def test_bad_model_output_fails_closed():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'output_text':'{"price":99}'}))) as http:
        with pytest.raises(RecognitionVisionError):
            await BookVisionClient(api_key='fixture',model='fixture-vision',http_client=http).observe_with_telemetry(['data:image/jpeg;base64,x'])


@pytest.mark.parametrize('images',[[],['x'*100]*4,['https://x'],['x'*4_000_001]])
def test_request_image_bounds(images):
    with pytest.raises(ValidationError): BookScanRequest(images=images)
