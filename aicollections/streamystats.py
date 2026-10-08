"""Recommendations from Streamystats' public API, in its own ranking order."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request


class Streamystats:
    def __init__(self, base_url: str, api_key: str, jellyfin_server_id: str, timeout: float = 180):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.jellyfin_server_id = jellyfin_server_id
        self.timeout = timeout

    def recommended_ids(self, user_id: str, limit: int) -> list[str]:
        """Item ids recommended to `user_id`, best first.

        Uses the full format: `format=ids` splits movies and series into
        separate lists and loses the ranking. An admin key may ask on behalf
        of any user (`targetUserId`); that user's own settings and library
        access apply.
        """
        params = urllib.parse.urlencode(
            {
                "jellyfinServerId": self.jellyfin_server_id,
                "targetUserId": user_id,
                "limit": limit,
                "type": "all",
                "includeBasedOn": "false",
            }
        )
        req = urllib.request.Request(
            f"{self.base_url}/api/recommendations?{params}",
            headers={"Authorization": f'MediaBrowser Token="{self.api_key}"'},
        )
        # Any failure raises: an error must never read as "no recommendations",
        # or the user's collection would be deleted. (A user Streamystats does
        # not know yet gets a 200 with an empty list.)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read())
        ids: list[str] = []
        for rec in body.get("data") or []:
            item_id = (rec.get("item") or {}).get("id")
            if isinstance(item_id, str) and item_id not in ids:
                ids.append(item_id)
        return ids[:limit]
