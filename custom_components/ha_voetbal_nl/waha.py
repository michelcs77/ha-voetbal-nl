"""WAHA client helpers for HA Voetbal.nl."""
from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientError, ClientSession


class WahaError(Exception):
    """Base WAHA error."""


class WahaClient:
    """Small async client for the WAHA endpoints used by this integration."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        api_key: str,
        session_name: str = "default",
        team_configs: dict | None = None,
    ):
        self._http = session
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session_name = session_name or "default"
        self.team_configs = dict(team_configs or {})

    @property
    def headers(self):
        return {"X-Api-Key": self.api_key}

    async def _json(self, method: str, path: str, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        try:
            async with self._http.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=20,
                **kwargs,
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise WahaError(f"WAHA HTTP {response.status}: {text[:300]}")
                if response.content_type == "application/json":
                    return await response.json()
                text = await response.text()
                return {"text": text}
        except ClientError as err:
            raise WahaError(str(err)) from err

    async def sessions(self):
        return await self._json("GET", "/api/sessions")

    async def session_info(self):
        return await self._json("GET", f"/api/sessions/{quote(self.session_name, safe='')}")

    async def groups(self):
        return await self._json("GET", f"/api/{quote(self.session_name, safe='')}/groups")

    async def send_poll(self, chat_id: str, question: str, options: list[str]):
        return await self._json(
            "POST",
            "/api/sendPoll",
            json={
                "session": self.session_name,
                "chatId": chat_id,
                "poll": {
                    "name": question,
                    "options": options,
                    "multipleAnswers": False,
                },
            },
        )

    async def send_file(
        self,
        chat_id: str,
        file_path: str,
        filename: str | None = None,
        caption: str = "",
        mimetype: str = "application/octet-stream",
    ):
        """Send a local file as a WhatsApp document through WAHA."""
        path = Path(file_path)
        if not path.is_file():
            raise WahaError(f"Bestand niet gevonden: {path}")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return await self._json(
            "POST",
            "/api/sendFile",
            json={
                "session": self.session_name,
                "chatId": chat_id,
                "caption": caption,
                "file": {
                    "mimetype": mimetype,
                    "filename": filename or path.name,
                    "data": data,
                },
            },
        )

    def _assistant_name_for_chat(self, chat_id: str) -> str:
        """Return the configured digital assistant name for the WhatsApp group."""
        chat_id = str(chat_id or "").strip()
        for team_cfg in self.team_configs.values():
            if not isinstance(team_cfg, dict):
                continue
            if chat_id in {
                str(team_cfg.get("test_group_id") or "").strip(),
                str(team_cfg.get("prod_group_id") or "").strip(),
            }:
                return (
                    str(team_cfg.get("assistant_name") or "De AI-Stafchef").strip()
                    or "De AI-Stafchef"
                )
        return "De AI-Stafchef"

    async def send_text(
        self,
        chat_id: str,
        text: str,
        team_name: str | None = None,
        reply_to: str | None = None,
    ):
        """Send text, optionally as a WhatsApp reply to an existing message."""
        assistant_name = self._assistant_name_for_chat(chat_id)
        team_label = str(team_name or "v.v. Cuijk").strip() or "v.v. Cuijk"
        signature = (
            f"🤖 **{assistant_name}**\n"
            f"Digitale stafassistent van {team_label}"
        )
        if signature not in text:
            text = f"{text.rstrip()}\n\n{signature}"
        payload = {
            "session": self.session_name,
            "chatId": chat_id,
            "text": text,
        }
        if reply_to:
            payload["reply_to"] = str(reply_to)
        return await self._json("POST", "/api/sendText", json=payload)

    async def pin_message(
        self, chat_id: str, message_id: str, duration: int = 604800
    ):
        """Pin a WhatsApp message (WEBJS/NOWEB). Default: seven days."""
        session = quote(self.session_name, safe="")
        chat = quote(str(chat_id), safe="")
        message = quote(str(message_id), safe="")
        return await self._json(
            "POST",
            f"/api/{session}/chats/{chat}/messages/{message}/pin",
            json={"duration": int(duration)},
        )

    async def unpin_message(self, chat_id: str, message_id: str):
        """Remove a WhatsApp message pin (WEBJS/NOWEB)."""
        session = quote(self.session_name, safe="")
        chat = quote(str(chat_id), safe="")
        message = quote(str(message_id), safe="")
        return await self._json(
            "POST",
            f"/api/{session}/chats/{chat}/messages/{message}/unpin",
        )

    async def resolve_lid(self, voter: str) -> str | None:
        if not voter:
            return None
        if voter.endswith("@c.us"):
            return voter
        if not voter.endswith("@lid"):
            return None
        lid = voter.split("@", 1)[0]
        data = await self._json(
            "GET", f"/api/{quote(self.session_name, safe='')}/lids/{quote(lid, safe='')}"
        )
        return data.get("pn") if isinstance(data, dict) else None

    async def contact(self, contact_id: str) -> dict:
        encoded = quote(contact_id, safe="")
        session = quote(self.session_name, safe="")
        data = await self._json(
            "GET", f"/api/contacts?contactId={encoded}&session={session}"
        )
        return data if isinstance(data, dict) else {}

    async def ensure_webhook(self, url: str, event: str = "poll.vote") -> bool:
        """Merge our webhook into existing session config; preserve all unrelated settings."""
        info = await self.session_info()
        config = dict(info.get("config") or {})
        webhooks = [dict(x) for x in config.get("webhooks", []) if isinstance(x, dict)]

        for item in webhooks:
            if item.get("url") == url:
                events = list(item.get("events") or [])
                if event in events:
                    return False
                events.append(event)
                item["events"] = list(dict.fromkeys(events))
                break
        else:
            webhooks.append({"url": url, "events": [event]})

        config["webhooks"] = webhooks
        await self._json(
            "PUT",
            f"/api/sessions/{quote(self.session_name, safe='')}",
            json={"name": self.session_name, "config": config},
        )
        return True
