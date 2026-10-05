import pytest

from app.social_media_specs import FORMATS, get_format, prompt_contract, validate_exact_dimensions


@pytest.mark.parametrize(
    ("key", "width", "height", "ratio"),
    [
        ("instagram_feed_image", 1080, 1350, "4:5"),
        ("instagram_carousel_slide", 1080, 1350, "4:5"),
        ("instagram_reel", 1080, 1920, "9:16"),
        ("instagram_story", 1080, 1920, "9:16"),
        ("tiktok_photo", 1080, 1920, "9:16"),
        ("tiktok_video", 1080, 1920, "9:16"),
        ("youtube_short", 1080, 1920, "9:16"),
    ],
)
def test_platform_native_contract(key, width, height, ratio):
    spec = get_format(key)
    assert (spec.width, spec.height, spec.aspect_ratio) == (width, height, ratio)
    validate_exact_dimensions(key, width=width, height=height)


@pytest.mark.parametrize(
    ("key", "width", "height"),
    [
        ("instagram_feed_image", 1080, 1920),
        ("tiktok_photo", 948, 1659),
        ("tiktok_video", 1080, 1350),
        ("youtube_short", 1920, 1080),
    ],
)
def test_approximate_or_wrong_channel_dimensions_fail_closed(key, width, height):
    with pytest.raises(ValueError, match="SOCIAL_FORMAT_DIMENSIONS_INVALID"):
        validate_exact_dimensions(key, width=width, height=height)


def test_unknown_format_fails_closed():
    with pytest.raises(ValueError, match="SOCIAL_FORMAT_UNKNOWN"):
        get_format("instagram_nearly_vertical")


def test_prompt_contract_names_every_publishable_canvas():
    text = prompt_contract()
    for key, spec in FORMATS.items():
        assert key in text
        assert f"{spec.width}x{spec.height}" in text
        assert spec.aspect_ratio in text
    assert "Never resize one finished composition across channels" in text
    assert "approximate dimensions" in text
