import hashlib
import io

import pytest
from PIL import Image, PngImagePlugin
from app.social_pilot_media import MediaIntegrityError, verify_png_pixels


def fixture():
    image=Image.new('RGB',(8,8),(16,32,48))
    image.putpixel((3,4),(190,120,7))
    asset={'width':8,'height':8,'mime_type':'image/png','integrity':'rgb8-sha256-v1',
           'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest()}
    return image,asset


def encode(image, **kwargs):
    stream=io.BytesIO(); image.save(stream,format='PNG',**kwargs); return stream.getvalue()


def test_lossless_reencoding_and_text_metadata_preserve_exact_approval():
    image,asset=fixture()
    first=encode(image,compress_level=0)
    metadata=PngImagePlugin.PngInfo(); metadata.add_text('Comment','CDN metadata is not an instruction')
    second=encode(image,compress_level=9,pnginfo=metadata)
    assert hashlib.sha256(first).digest()!=hashlib.sha256(second).digest()
    assert verify_png_pixels(first,asset)['rgb_sha256']==verify_png_pixels(second,asset)['rgb_sha256']


def test_one_pixel_difference_is_rejected():
    image,asset=fixture(); image.putpixel((0,0),(17,32,48))
    with pytest.raises(MediaIntegrityError,match='PIXELS_CHANGED'): verify_png_pixels(encode(image),asset)


def test_dimension_change_is_rejected_before_loading():
    image,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='DIMENSIONS_CHANGED'): verify_png_pixels(encode(image.resize((9,8))),asset)


def test_fully_opaque_rgba_is_identical():
    image,asset=fixture()
    assert verify_png_pixels(encode(image.convert('RGBA')),asset)['rgb_sha256']==asset['rgb_sha256']


def test_partial_alpha_is_rejected():
    image,asset=fixture(); image=image.convert('RGBA'); image.putpixel((0,0),(16,32,48,254))
    with pytest.raises(MediaIntegrityError,match='TRANSPARENCY_CHANGED'): verify_png_pixels(encode(image),asset)


def test_animation_is_rejected():
    image,asset=fixture(); other=image.copy(); other.putpixel((0,0),(17,32,48))
    body=encode(image,save_all=True,append_images=[other],duration=100,loop=0)
    with pytest.raises(MediaIntegrityError,match='ANIMATION_FORBIDDEN'): verify_png_pixels(body,asset)


def test_colour_profile_is_rejected():
    image,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='COLOUR_METADATA_CHANGED'): verify_png_pixels(encode(image,icc_profile=b'not-approved-profile'),asset)


@pytest.mark.parametrize('body',[b'not image',b'\xff\xd8\xff jpeg'])
def test_wrong_format_is_rejected(body):
    _,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='FORMAT_INVALID'): verify_png_pixels(body,asset)


def test_bad_png_is_rejected():
    _,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='DECODE_FAILED'): verify_png_pixels(b'\x89PNG\r\n\x1a\ninvalid',asset)


def test_encoded_bound_is_enforced():
    _,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='TOO_LARGE'): verify_png_pixels(b'x'*(8*1024*1024+1),asset)


@pytest.mark.parametrize('change',[{'width':0},{'height':True},{'width':20_000_000},
    {'rgb_sha256':'invalid'},{'integrity':'perceptual'},{'mime_type':'image/jpeg'}])
def test_invalid_approval_is_rejected(change):
    image,asset=fixture(); asset.update(change)
    with pytest.raises(MediaIntegrityError,match='APPROVAL_INVALID'): verify_png_pixels(encode(image),asset)
