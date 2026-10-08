"""One reconciliation pass: every user gets exactly one private collection of
their recommendations, or none when they have no recommendations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import plan
from .collage import TILE_H, TILE_W, collage
from .plan import COVER_PROVIDER_KEY, OWNER_PROVIDER_KEY, User

log = logging.getLogger("aicollections")


@dataclass
class Config:
    display_name: str = "AI Recommendations"
    size: int = 30
    tag_prefix: str = ".hide-from-"


@dataclass
class Result:
    collections: int = 0
    removed: int = 0
    policies_changed: int = 0
    errors: list[str] = field(default_factory=list)


def _owned_collections(jf, users: list[User], cfg: Config) -> dict[str, dict]:
    """Collections this service manages, by owner id. Adopts collections made
    before the ownership marker existed (identified by folder name)."""
    by_owner: dict[str, dict] = {}
    for col in jf.collections():
        providers = col.get("ProviderIds") or {}
        owner_id = providers.get(OWNER_PROVIDER_KEY)
        if not owner_id:
            legacy = plan.legacy_owner(col.get("Path") or "", users, cfg.display_name)
            owner_id = legacy.id if legacy else None
        if not owner_id:
            continue
        if owner_id in by_owner:
            # Never more than one per user: drop duplicates.
            jf.delete_item(col["Id"])
            continue
        by_owner[owner_id] = col
    return by_owner


def reconcile_policies(jf, cfg: Config, remove: bool = False) -> int:
    """Each user blocks exactly their own hide tag (none when removing)."""
    changed = 0
    for u in jf.users():
        policy = u.get("Policy") or {}
        current = [t for t in policy.get("BlockedTags") or [] if isinstance(t, str)]
        own = None if remove else plan.hide_tag(User(u["Id"], u["Name"]), cfg.tag_prefix)
        wanted = plan.reconcile_blocked_tags(current, own, cfg.tag_prefix)
        if plan.same_tags(current, wanted):
            continue
        jf.update_policy(u["Id"], {**policy, "BlockedTags": wanted})
        changed += 1
    return changed


def _apply_metadata(jf, collection_id: str, owner: User, tags: list[str], cfg: Config,
                    cover: str | None = None) -> dict:
    """Name, hide tags and ownership marker on the collection itself; locked so
    metadata refreshes keep them. Read as the owner, the one user it is never
    hidden from."""
    dto = jf.item(collection_id, owner.id)
    if dto is None:
        raise RuntimeError(f"collection {collection_id} disappeared")
    providers = dict(dto.get("ProviderIds") or {})
    providers[OWNER_PROVIDER_KEY] = owner.id
    if cover is not None:
        providers[COVER_PROVIDER_KEY] = cover
    locked = set(dto.get("LockedFields") or []) | {"Name", "Tags"}
    changed = (
        dto.get("Name") != cfg.display_name
        or not plan.same_tags(dto.get("Tags") or [], tags)
        or (dto.get("ProviderIds") or {}) != providers
        or set(dto.get("LockedFields") or []) != locked
    )
    if changed:
        jf.update_item(
            collection_id,
            {**dto, "Name": cfg.display_name, "Tags": tags,
             "ProviderIds": providers, "LockedFields": sorted(locked)},
        )
    return {**dto, "ProviderIds": providers}


def _ensure_collection(jf, owner: User, existing: dict | None, tags: list[str], cfg: Config) -> tuple[str, dict]:
    if existing and jf.item(existing["Id"], owner.id) is not None:
        return existing["Id"], _apply_metadata(jf, existing["Id"], owner, tags, cfg)
    # Created empty and hidden before anything goes in; deleted again rather
    # than ever left visible if hiding fails.
    collection_id = jf.create_collection(plan.folder_name(cfg.display_name, owner))
    try:
        dto = _apply_metadata(jf, collection_id, owner, tags, cfg)
    except Exception:
        jf.delete_item(collection_id)
        raise
    return collection_id, dto


def _update_cover(jf, collection_id: str, owner: User, dto: dict, ids: list[str], tags, cfg) -> None:
    """Collage of the top picks, redrawn only when they change."""
    key = plan.cover_key(ids)
    if (dto.get("ProviderIds") or {}).get(COVER_PROVIDER_KEY) == key:
        return
    posters = [p for p in (jf.poster(i, TILE_W, TILE_H) for i in ids[:4]) if p]
    image = collage(posters)
    if image is None:
        return
    jf.set_primary_image(collection_id, image)
    _apply_metadata(jf, collection_id, owner, tags, cfg, cover=key)


def run(jf, recs, cfg: Config) -> Result:
    result = Result()
    # Users block their own tag before any tagged collection is created or changed.
    result.policies_changed = reconcile_policies(jf, cfg)
    users = [User(u["Id"], u["Name"]) for u in jf.users()]
    owned = _owned_collections(jf, users, cfg)
    user_ids = {u.id for u in users}

    for owner_id, col in owned.items():
        if owner_id not in user_ids:
            jf.delete_item(col["Id"])
            result.removed += 1

    # Fetch everyone's picks first. A failed fetch keeps that user's
    # collection as it is.
    picks: dict[str, list[str]] = {}
    for user in users:
        try:
            picks[user.id] = recs.recommended_ids(user.id, cfg.size)
        except Exception as e:
            log.error("recommendations for %s failed: %s", user.name, e)
            result.errors.append(f"{user.name}: {e}")
    # Circuit breaker: Streamystats answers 200 with an empty list when it
    # fails internally. Nothing for anyone while collections exist means it is
    # broken, not that every user stopped having recommendations.
    if owned and picks and not any(picks.values()):
        msg = "Streamystats returned no recommendations for any user; leaving collections unchanged"
        log.error(msg)
        result.errors.append(msg)
        return result

    for user in users:
        if user.id not in picks:
            continue
        try:
            ids = picks[user.id]
            existing = owned.get(user.id)
            if not ids:
                if existing:
                    jf.delete_item(existing["Id"])
                    result.removed += 1
                continue
            tags = plan.collection_tags(user, users, cfg.tag_prefix)
            collection_id, dto = _ensure_collection(jf, user, existing, tags, cfg)
            add, drop = plan.membership_diff(jf.members(collection_id, user.id), ids)
            jf.add_members(collection_id, add)
            jf.remove_members(collection_id, drop)
            try:
                _update_cover(jf, collection_id, user, dto, ids, tags, cfg)
            except Exception as e:  # a cover is not worth failing the user over
                log.warning("cover for %s failed: %s", user.name, e)
            result.collections += 1
        except Exception as e:
            log.error("user %s failed: %s", user.name, e)
            result.errors.append(f"{user.name}: {e}")
    return result


def remove_all(jf, cfg: Config) -> Result:
    """Undo everything: delete managed collections and our blocked tags."""
    result = Result()
    users = [User(u["Id"], u["Name"]) for u in jf.users()]
    for col in _owned_collections(jf, users, cfg).values():
        jf.delete_item(col["Id"])
        result.removed += 1
    result.policies_changed = reconcile_policies(jf, cfg, remove=True)
    return result
