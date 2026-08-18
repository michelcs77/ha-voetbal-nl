"""Minimal Gemini text client used for optional coach messages."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp


class GeminiError(Exception):
    """Raised when Gemini cannot provide a usable response."""


class GeminiClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str, model: str = "gemini-3.6-flash"):
        self._session = session
        self._api_key = str(api_key or "").strip()
        self._model = str(model or "gemini-3.6-flash").strip()
        if self._model == "gemini-2.5-flash":
            self._model = "gemini-3.6-flash"

    @property
    def model(self) -> str:
        return self._model

    async def validate(self) -> None:
        if not self._api_key:
            raise GeminiError("Gemini API-key ontbreekt.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self._model, safe='.-_')}"
        try:
            async with self._session.get(url, headers={"x-goog-api-key": self._api_key}, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status >= 400:
                    text = (await resp.text())[:300]
                    raise GeminiError(f"Gemini model/API-key test mislukt ({resp.status}): {text}")
        except aiohttp.ClientError as err:
            raise GeminiError(f"Gemini verbinding mislukt: {err}") from err

    async def generate_coach_message(self, prompt: str) -> str:
        if not self._api_key:
            raise GeminiError("Gemini API-key ontbreekt.")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self._model, safe='.-_')}:generateContent"
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 900,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }
        try:
            async with self._session.post(
                url,
                headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    detail = str((data or {}).get("error", {}).get("message") or "")[:500]
                    raise GeminiError(f"Gemini generatie mislukt ({resp.status}): {detail}")
        except aiohttp.ClientError as err:
            raise GeminiError(f"Gemini verbinding mislukt: {err}") from err
        try:
            candidates = data.get("candidates") or []
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
            text = "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        except (IndexError, AttributeError, TypeError):
            text = ""
        if not text:
            raise GeminiError("Gemini gaf geen coachtekst terug.")
        # Keep WhatsApp output compact even if the model ignores the requested length.
        words = text.split()
        if len(words) > 110:
            text = " ".join(words[:110]).rstrip(" ,;:") + "…"
        return text.strip().strip('"')
