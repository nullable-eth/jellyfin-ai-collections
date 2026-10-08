"""Pure decisions: tags, ownership markers and membership. No I/O here.

Jellyfin has no per-collection permissions, but parental control can block
items by tag, and that applies to collections themselves. Each user's
collection is tagged `<prefix><other>` for every other user, and each user
blocks only their own `<prefix><self>` tag: one blocked tag per user, however
many users there are.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Markers on the collection itself (not shown in Jellyfin's UI), so ownership
# and the current cover survive restarts without a database.
OWNER_PROVIDER_KEY = "AiRecommendationsUser"
COVER_PROVIDER_KEY = "AiRecommendationsCover"


@dataclass(frozen=True)
class User:
    id: str
    name: str


def hide_tag(user: User, prefix: str) -> str:
    """`.hide-from-<slug>`; the user id when the name has nothing usable."""
    ascii_name = (
        unicodedata.normalize("NFKD", user.name).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return f"{prefix}{slug or user.id}"


def collection_tags(owner: User, users: list[User], prefix: str) -> list[str]:
    """Tags for `owner`'s collection: hidden from every other user."""
    own = hide_tag(owner, prefix)
    tags = {hide_tag(u, prefix) for u in users if u.id != owner.id}
    # A name collision must never hide the collection from its owner.
    tags.discard(own)
    return sorted(tags)


def reconcile_blocked_tags(
    current: list[str], own_tag: str | None, prefix: str
) -> list[str]:
    """Exactly the user's own hide tag among ours (none when removing).

    Tags an admin set by hand are kept untouched.
    """
    kept = [t for t in current if not t.startswith(prefix)]
    return kept + [own_tag] if own_tag else kept


def same_tags(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)


def membership_diff(current: list[str], wanted: list[str]) -> tuple[list[str], list[str]]:
    """(to add, to remove) so the collection holds exactly `wanted`."""
    have, want = set(current), set(wanted)
    return [i for i in wanted if i not in have], [i for i in current if i not in want]


def folder_name(display_name: str, user: User) -> str:
    """Name a collection is created with. Jellyfin stores each collection in a
    folder named after it, so this stays unique; the display name is then set
    separately."""
    return f"{display_name} {user.id}"


def legacy_owner(path: str, users: list[User], display_name: str) -> User | None:
    """Owner of a collection created before ownership markers existed
    (folder `<name> <userId> [boxset]` or `<name> for <userName> [boxset]`)."""
    folder = path.rstrip("/").rsplit("/", 1)[-1]
    if not folder.endswith(" [boxset]"):
        return None
    stem = folder[: -len(" [boxset]")]
    for user in users:
        if stem in (f"{display_name} {user.id}", f"{display_name} for {user.name}"):
            return user
    return None


def cover_key(item_ids: list[str]) -> str:
    return ",".join(item_ids[:4])
