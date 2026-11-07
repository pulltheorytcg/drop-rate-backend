"""Bounded lossless-media validation for the explicitly approved image pilot.

Encoded PNG metadata/compression may change; approved dimensions and EVERY sRGB
pixel must remain identical. This is not a perceptual or tolerance-based check.
"""
from __future__ import annotations

import hashlib
import io
import re
import warnings

from PIL import Image, ImageCms, UnidentifiedImageError

MAX_ENCODED_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000


class MediaIntegrityError(Exception):
    pass


def verify_png_pixels(body: bytes | bytearray, asset: dict) -> dict:
    if (asset.get('integrity') != 'rgb8-sha256-v1'
            or asset.get('mime_type') != 'image/png'
            or not re.fullmatch(r'[0-9a-f]{64}', str(asset.get('rgb_sha256', '')))):
        raise MediaIntegrityError('PILOT_MEDIA_APPROVAL_INVALID')
    width, height = asset.get('width'), asset.get('height')
    if (type(width) is not int or type(height) is not int
            or width <= 0 or height <= 0 or width * height > MAX_PIXELS):
        raise MediaIntegrityError('PILOT_MEDIA_APPROVAL_INVALID')
    if not body or len(body) > MAX_ENCODED_BYTES:
        raise MediaIntegrityError('PILOT_MEDIA_TOO_LARGE')
    if not body.startswith(b'\x89PNG\r\n\x1a\n'):
        raise MediaIntegrityError('PILOT_MEDIA_FORMAT_INVALID')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body), formats=['PNG']) as image:
                if image.size != (width, height):
                    raise MediaIntegrityError('PILOT_MEDIA_DIMENSIONS_CHANGED')
                if getattr(image, 'n_frames', 1) != 1:
                    raise MediaIntegrityError('PILOT_MEDIA_ANIMATION_FORBIDDEN')
                if image.mode not in {'RGB', 'RGBA', 'P'}:
                    raise MediaIntegrityError('PILOT_MEDIA_FORMAT_INVALID')
                if image.getexif().get(274, 1) != 1:
                    raise MediaIntegrityError('PILOT_MEDIA_COLOUR_METADATA_CHANGED')
                profile_bytes = image.info.get('icc_profile')
                gamma = image.info.get('gamma')
                if not profile_bytes and gamma is not None and abs(float(gamma) - 0.45455) > 0.00001:
                    raise MediaIntegrityError('PILOT_MEDIA_COLOUR_METADATA_CHANGED')
                image.load()
                rgba = image.convert('RGBA')
                if rgba.getchannel('A').getextrema() != (255, 255):
                    raise MediaIntegrityError('PILOT_MEDIA_TRANSPARENCY_CHANGED')
                rgb = rgba.convert('RGB')
                if profile_bytes:
                    if not isinstance(profile_bytes, bytes) or len(profile_bytes) > 128 * 1024:
                        raise MediaIntegrityError('PILOT_MEDIA_COLOUR_METADATA_CHANGED')
                    try:
                        # Honour the embedded profile, then require EXACT approved
                        # sRGB pixels. Merely naming a profile sRGB cannot bypass this.
                        profile = ImageCms.ImageCmsProfile(io.BytesIO(profile_bytes))
                        rgb = ImageCms.profileToProfile(rgb, profile, ImageCms.createProfile('sRGB'),
                            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC, outputMode='RGB')
                    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
                        raise MediaIntegrityError('PILOT_MEDIA_COLOUR_METADATA_CHANGED') from None
                actual = hashlib.sha256(rgb.tobytes()).hexdigest()
                if actual != asset['rgb_sha256']:
                    raise MediaIntegrityError('PILOT_MEDIA_PIXELS_CHANGED')
        return {'rgb_sha256': actual, 'width': width, 'height': height,
                'encoded_sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
    except MediaIntegrityError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, TypeError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise MediaIntegrityError('PILOT_MEDIA_DECODE_FAILED') from None
