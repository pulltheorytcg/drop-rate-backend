import hashlib
import io

import pytest
from PIL import Image, ImageCms, PngImagePlugin
from app.social_pilot_media import MediaIntegrityError, verify_png_pixels


def fixture():
    image=Image.new('RGB',(16,16),(32,80,190)); image.putpixel((1,1),(200,140,10))
    asset={'width':16,'height':16,'mime_type':'image/png','integrity':'rgb8-sha256-v1',
           'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest()}
    return image,asset


def encode(image,**kwargs):
    f=io.BytesIO(); image.save(f,format='PNG',**kwargs); return f.getvalue()


def srgb_profile():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def test_cdn_standard_srgb_profile_keeps_exact_pixels():
    image,asset=fixture()
    assert verify_png_pixels(encode(image,icc_profile=srgb_profile()),asset)['rgb_sha256']==asset['rgb_sha256']


def test_harmless_exif_and_identity_orientation_are_allowed():
    image,asset=fixture(); exif=Image.Exif(); exif[274]=1; exif[305]='CDN encoder'
    assert verify_png_pixels(encode(image,exif=exif),asset)['rgb_sha256']==asset['rgb_sha256']


def test_changed_orientation_still_rejected():
    image,asset=fixture(); exif=Image.Exif(); exif[274]=6
    with pytest.raises(MediaIntegrityError,match='METADATA_CHANGED'): verify_png_pixels(encode(image,exif=exif),asset)


def test_profile_transform_cannot_change_even_one_value(monkeypatch):
    image,asset=fixture()
    changed=image.copy(); changed.putpixel((0,0),(33,80,190))
    monkeypatch.setattr(ImageCms,'profileToProfile',lambda *args,**kwargs:changed)
    with pytest.raises(MediaIntegrityError,match='PIXELS_CHANGED'): verify_png_pixels(encode(image,icc_profile=srgb_profile()),asset)


def test_oversized_profile_rejected():
    image,asset=fixture()
    with pytest.raises(MediaIntegrityError,match='METADATA_CHANGED'): verify_png_pixels(encode(image,icc_profile=b'x'*(128*1024+1)),asset)


def test_nonstandard_unprofiled_gamma_rejected():
    import struct
    image,asset=fixture(); info=PngImagePlugin.PngInfo(); info.add(b'gAMA',struct.pack('>I',60000))
    with pytest.raises(MediaIntegrityError,match='METADATA_CHANGED'): verify_png_pixels(encode(image,pnginfo=info),asset)
