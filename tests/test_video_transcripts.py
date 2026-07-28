from app.services.video_transcripts import parse_vtt, youtube_video_id


def test_youtube_video_id_rejects_channels_and_accepts_short_urls():
    assert youtube_video_id("https://youtu.be/7DLU4tfEIVY") == "7DLU4tfEIVY"
    assert youtube_video_id("https://www.youtube.com/watch?v=7DLU4tfEIVY") == "7DLU4tfEIVY"
    assert youtube_video_id("https://www.youtube.com/@ScienceOlympiadTV") is None


def test_parse_vtt_strips_markup_and_deduplicates_rollup_captions():
    payload = """WEBVTT

00:00:01.000 --> 00:00:03.000
Hello <b>world</b>

00:00:03.000 --> 00:00:04.000
Hello <b>world</b>
"""
    assert parse_vtt(payload) == [{"start": 1.0, "end": 3.0, "text": "Hello world"}]
