"""Phase V — Deepgram narration: Aura TTS plus word-level timings for caption sync.

Aura returns audio only, so word timings come from a second pass: we send the synthesized
audio back through Deepgram's transcription endpoint, which yields per-word start/end times
aligned to that exact audio. That alignment is what keeps captions locked to the narration.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings

SPEAK_URL = "https://api.deepgram.com/v1/speak"
LISTEN_URL = "https://api.deepgram.com/v1/listen"


class DeepgramError(RuntimeError):
    pass


@dataclass
class Narration:
    audio: bytes
    words: list[dict] = field(default_factory=list)
    model: str = ""

    @property
    def duration(self) -> float:
        return max((float(w.get("endSeconds", 0.0)) for w in self.words), default=0.0)


class DeepgramNarrator:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.deepgram_api_key
        self.model = model or settings.deepgram_tts_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Token {self.api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def synthesize(self, text: str) -> bytes:
        """Aura TTS → audio bytes (mp3)."""
        if not self.configured:
            raise DeepgramError("Deepgram is not configured")
        if not text.strip():
            raise DeepgramError("narration text is empty")
        try:
            response = httpx.post(
                SPEAK_URL,
                params={"model": self.model, "encoding": "mp3"},
                headers=self._headers("application/json"),
                json={"text": text},
                timeout=httpx.Timeout(120.0, connect=15.0),
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise DeepgramError(f"Deepgram speak failed: {exc}") from exc

    def align(self, audio: bytes) -> list[dict]:
        """Transcribe the synthesized audio to recover per-word start/end times."""
        if not self.configured:
            raise DeepgramError("Deepgram is not configured")
        try:
            response = httpx.post(
                LISTEN_URL,
                params={"model": "nova-2", "punctuate": "true", "smart_format": "false"},
                headers=self._headers("audio/mpeg"),
                content=audio,
                timeout=httpx.Timeout(180.0, connect=15.0),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DeepgramError(f"Deepgram alignment failed: {exc}") from exc
        return parse_word_timings(payload)

    def narrate(self, text: str) -> Narration:
        """Synthesize and align in one step — what the render pipeline calls per scene."""
        audio = self.synthesize(text)
        try:
            words = self.align(audio)
        except DeepgramError:
            words = []  # captions degrade, narration still renders
        return Narration(audio=audio, words=words, model=self.model)


def parse_word_timings(payload: dict) -> list[dict]:
    """Extract [{text,startSeconds,endSeconds}] from a Deepgram transcription response."""
    try:
        alternatives = payload["results"]["channels"][0]["alternatives"]
    except (KeyError, IndexError, TypeError):
        return []
    if not alternatives:
        return []
    words = alternatives[0].get("words") or []
    out: list[dict] = []
    for word in words:
        text = word.get("punctuated_word") or word.get("word")
        if not text:
            continue
        out.append({
            "text": str(text),
            "startSeconds": round(float(word.get("start", 0.0)), 3),
            "endSeconds": round(float(word.get("end", 0.0)), 3),
        })
    return out
