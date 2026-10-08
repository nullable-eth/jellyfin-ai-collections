"""Minimal Jellyfin API client (stdlib only).

Reads of a collection and its members go through the owner's user context:
Jellyfin 10.11 rejects `GET /Items/{id}` without a user and lists no members.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class JellyfinError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Jellyfin {status}: {message}")
        self.status = status


class Jellyfin:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"X-Emby-Token": self.api_key}
        if body is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            raise JellyfinError(e.code, e.read().decode(errors="replace")[:300]) from e
        if not data:
            return None
        try:
            return json.loads(data)
        except ValueError:
            return data

    def _json(self, method: str, path: str, payload: Any, **params: Any) -> Any:
        return self._request(method, path, params, json.dumps(payload).encode())

    # -- server & users
    def server_id(self) -> str:
        return self._request("GET", "/System/Info/Public")["Id"]

    def users(self) -> list[dict]:
        return self._request("GET", "/Users") or []

    def update_policy(self, user_id: str, policy: dict) -> None:
        # Jellyfin replaces the whole policy, so callers pass the full object.
        self._json("POST", f"/Users/{user_id}/Policy", policy)

    # -- collections
    def collections(self) -> list[dict]:
        resp = self._request(
            "GET",
            "/Items",
            {"Recursive": "true", "IncludeItemTypes": "BoxSet", "Fields": "Path,ProviderIds"},
        )
        return (resp or {}).get("Items", [])

    def create_collection(self, name: str) -> str:
        return self._request("POST", "/Collections", {"Name": name})["Id"]

    def item(self, item_id: str, user_id: str) -> dict | None:
        try:
            return self._request("GET", f"/Items/{item_id}", {"userId": user_id})
        except JellyfinError as e:
            if e.status == 404:
                return None
            raise

    def update_item(self, item_id: str, dto: dict) -> None:
        self._json("POST", f"/Items/{item_id}", dto)

    def members(self, collection_id: str, user_id: str) -> list[str]:
        resp = self._request(
            "GET",
            "/Items",
            {"ParentId": collection_id, "userId": user_id, "Recursive": "false", "Limit": 1000},
        )
        return [i["Id"] for i in (resp or {}).get("Items", [])]

    def add_members(self, collection_id: str, ids: list[str]) -> None:
        if ids:
            self._request("POST", f"/Collections/{collection_id}/Items", {"Ids": ",".join(ids)})

    def remove_members(self, collection_id: str, ids: list[str]) -> None:
        if ids:
            self._request("DELETE", f"/Collections/{collection_id}/Items", {"Ids": ",".join(ids)})

    def delete_item(self, item_id: str) -> None:
        try:
            self._request("DELETE", f"/Items/{item_id}")
        except JellyfinError as e:
            if e.status != 404:
                raise

    # -- images
    def poster(self, item_id: str, width: int, height: int) -> bytes | None:
        try:
            data = self._request(
                "GET",
                f"/Items/{item_id}/Images/Primary",
                {"fillWidth": width, "fillHeight": height, "quality": 90},
            )
        except JellyfinError:
            return None
        return data if isinstance(data, bytes) else None

    def set_primary_image(self, item_id: str, jpeg: bytes) -> None:
        # Jellyfin takes the image as a base64 body with the image content type.
        self._request(
            "POST",
            f"/Items/{item_id}/Images/Primary",
            body=base64.b64encode(jpeg),
            content_type="image/jpeg",
        )
