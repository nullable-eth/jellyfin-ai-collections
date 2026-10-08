"""Tests with an in-memory Jellyfin that records every call, so ordering
(hidden before filled) is checked, not just end state.

Run: python -m unittest discover -s tests
"""

import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicollections import plan  # noqa: E402
from aicollections.plan import COVER_PROVIDER_KEY, OWNER_PROVIDER_KEY, User  # noqa: E402
from aicollections.retry import with_retries  # noqa: E402
from aicollections.sync import Config, remove_all, run  # noqa: E402

PREFIX = ".hide-from-"


def poster_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (200, 300), (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


class FakeJellyfin:
    def __init__(self, users, collections=None):
        self._users = {u["Id"]: u for u in users}
        self.cols = {c["Id"]: c for c in (collections or [])}
        self.calls = []
        self.fail_metadata = False
        self.posters = 0
        self._next = 0

    # users
    def users(self):
        return [dict(u) for u in self._users.values()]

    def update_policy(self, user_id, policy):
        self.calls.append(("policy", user_id))
        self._users[user_id]["Policy"] = policy

    # collections
    def collections(self):
        return [{"Id": c["Id"], "Path": c["Path"], "ProviderIds": dict(c["ProviderIds"])}
                for c in self.cols.values()]

    def create_collection(self, name):
        self._next += 1
        cid = f"c{self._next}"
        self.cols[cid] = {"Id": cid, "Name": name, "Path": f"/config/data/collections/{name} [boxset]",
                          "Tags": [], "ProviderIds": {}, "LockedFields": [], "Members": []}
        self.calls.append(("create", cid))
        return cid

    def item(self, cid, user_id):
        c = self.cols.get(cid)
        return None if c is None else {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                                       for k, v in c.items() if k != "Members"}

    def update_item(self, cid, dto):
        if self.fail_metadata:
            raise RuntimeError("boom")
        self.calls.append(("update", cid))
        c = self.cols[cid]
        for k in ("Name", "Tags", "ProviderIds", "LockedFields"):
            c[k] = dto[k]

    def members(self, cid, user_id):
        return list(self.cols[cid]["Members"])

    def add_members(self, cid, ids):
        if ids:
            self.calls.append(("add", cid))
            self.cols[cid]["Members"] += ids

    def remove_members(self, cid, ids):
        self.cols[cid]["Members"] = [m for m in self.cols[cid]["Members"] if m not in ids]

    def delete_item(self, cid):
        self.calls.append(("delete", cid))
        self.cols.pop(cid, None)

    def poster(self, item_id, w, h):
        self.posters += 1
        return poster_bytes()

    def set_primary_image(self, cid, jpeg):
        self.calls.append(("image", cid))


class FakeRecs:
    def __init__(self, by_user, failing=()):
        self.by_user = by_user
        self.failing = set(failing)

    def recommended_ids(self, user_id, limit):
        if user_id in self.failing:
            raise OSError("connection refused")
        return self.by_user.get(user_id, [])[:limit]


def jf_user(uid, name, blocked=None):
    return {"Id": uid, "Name": name, "Policy": {"BlockedTags": blocked or [], "IsAdministrator": False}}


def owned(jf, uid):
    return [c for c in jf.cols.values() if c["ProviderIds"].get(OWNER_PROVIDER_KEY) == uid]


class PlanTests(unittest.TestCase):
    def test_hide_tag_slugs_name_or_falls_back_to_id(self):
        self.assertEqual(plan.hide_tag(User("n1", "nullable.eth"), PREFIX), ".hide-from-nullable-eth")
        self.assertEqual(plan.hide_tag(User("z", "Zoë Ann"), PREFIX), ".hide-from-zoe-ann")
        self.assertEqual(plan.hide_tag(User("abc", "★★"), PREFIX), ".hide-from-abc")

    def test_collection_hidden_from_everyone_but_owner(self):
        users = [User("s", "Sarah"), User("n", "nullable.eth"), User("k", "Kids")]
        self.assertEqual(plan.collection_tags(users[1], users, PREFIX), [".hide-from-kids", ".hide-from-sarah"])

    def test_name_collision_never_hides_from_owner(self):
        users = [User("s", "Sarah"), User("t", "sarah!")]
        self.assertEqual(plan.collection_tags(users[0], users, PREFIX), [])

    def test_blocked_tags_keep_hand_set_and_replace_stale(self):
        self.assertEqual(plan.reconcile_blocked_tags([".no-share", ".hide-from-sara"], ".hide-from-sarah", PREFIX),
                         [".no-share", ".hide-from-sarah"])
        self.assertEqual(plan.reconcile_blocked_tags([".no-share", ".hide-from-sarah"], None, PREFIX), [".no-share"])

    def test_legacy_owner_from_folder_name(self):
        users = [User("n1", "nullable.eth")]
        self.assertEqual(plan.legacy_owner("/c/AI Recommendations for nullable.eth [boxset]", users,
                                           "AI Recommendations"), users[0])
        self.assertEqual(plan.legacy_owner("/c/AI Recommendations n1 [boxset]", users, "AI Recommendations"), users[0])
        self.assertIsNone(plan.legacy_owner("/c/Gio [boxset]", users, "AI Recommendations"))


class RetryTests(unittest.TestCase):
    def test_rides_out_connection_refused(self):
        import urllib.error
        attempts, slept = [], []

        def flaky():
            attempts.append(1)
            if len(attempts) < 3:
                raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
            return "ok"

        self.assertEqual(with_retries(flaky, "test", sleep=slept.append), "ok")
        self.assertEqual(slept, [5.0, 15.0])

    def test_does_not_retry_client_errors(self):
        import urllib.error
        attempts = []

        def unauthorized():
            attempts.append(1)
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        with self.assertRaises(urllib.error.HTTPError):
            with_retries(unauthorized, "test", sleep=lambda s: None)
        self.assertEqual(len(attempts), 1)

    def test_gives_up_after_the_last_delay(self):
        import urllib.error
        attempts = []

        def down():
            attempts.append(1)
            raise urllib.error.URLError("refused")

        with self.assertRaises(urllib.error.URLError):
            with_retries(down, "test", sleep=lambda s: None)
        self.assertEqual(len(attempts), 4)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_new_collection_is_hidden_before_anything_goes_in(self):
        jf = FakeJellyfin([jf_user("s", "Sarah", [".no-share"]), jf_user("n", "nullable.eth")])
        result = run(jf, FakeRecs({"n": ["a", "b", "c", "d", "e"]}), self.cfg)
        self.assertEqual(result.collections, 1)
        [col] = owned(jf, "n")
        self.assertEqual(col["Name"], "AI Recommendations")
        self.assertEqual(col["Tags"], [".hide-from-sarah"])
        self.assertEqual(col["Members"], ["a", "b", "c", "d", "e"])
        order = [c for c in jf.calls if c[1] == col["Id"]]
        self.assertLess(order.index(("update", col["Id"])), order.index(("add", col["Id"])))
        # Every user blocks exactly their own tag; hand-set tags survive.
        self.assertEqual(jf._users["s"]["Policy"]["BlockedTags"], [".no-share", ".hide-from-sarah"])
        self.assertEqual(jf._users["n"]["Policy"]["BlockedTags"], [".hide-from-nullable-eth"])

    def test_failed_hiding_deletes_the_new_collection(self):
        jf = FakeJellyfin([jf_user("s", "Sarah"), jf_user("n", "nullable.eth")])
        jf.fail_metadata = True
        result = run(jf, FakeRecs({"n": ["a"]}), self.cfg)
        self.assertEqual(jf.cols, {})
        self.assertEqual(len(result.errors), 1)

    def test_adopts_legacy_collection_instead_of_duplicating(self):
        legacy = {"Id": "old", "Name": "AI Recommendations", "Tags": [".hide-from-sarah"], "LockedFields": [],
                  "Path": "/config/data/collections/AI Recommendations for nullable.eth [boxset]",
                  "ProviderIds": {}, "Members": ["a", "z"]}
        jf = FakeJellyfin([jf_user("s", "Sarah"), jf_user("n", "nullable.eth")], [legacy])
        run(jf, FakeRecs({"n": ["a", "b"]}), self.cfg)
        self.assertEqual(list(jf.cols), ["old"])
        self.assertEqual(jf.cols["old"]["ProviderIds"][OWNER_PROVIDER_KEY], "n")
        self.assertEqual(jf.cols["old"]["Members"], ["a", "b"])

    def test_new_user_is_tagged_out_of_existing_collections(self):
        jf = FakeJellyfin([jf_user("s", "Sarah"), jf_user("n", "nullable.eth")])
        recs = FakeRecs({"n": ["a"]})
        run(jf, recs, self.cfg)
        jf._users["t"] = jf_user("t", "Tom")
        run(jf, recs, self.cfg)
        [col] = owned(jf, "n")
        self.assertEqual(col["Tags"], [".hide-from-sarah", ".hide-from-tom"])
        self.assertIn(".hide-from-tom", jf._users["t"]["Policy"]["BlockedTags"])

    def test_cover_redrawn_only_when_top_four_change(self):
        jf = FakeJellyfin([jf_user("n", "nullable.eth")])
        recs = FakeRecs({"n": ["a", "b", "c", "d", "e"]})
        run(jf, recs, self.cfg)
        self.assertEqual(jf.posters, 4)
        [col] = owned(jf, "n")
        self.assertEqual(col["ProviderIds"][COVER_PROVIDER_KEY], "a,b,c,d")
        recs.by_user["n"] = ["a", "b", "c", "d", "f"]  # only below the top four
        run(jf, recs, self.cfg)
        self.assertEqual(jf.posters, 4)
        recs.by_user["n"] = ["x", "a", "b", "c"]
        run(jf, recs, self.cfg)
        self.assertEqual(jf.posters, 8)

    def test_second_run_changes_nothing(self):
        jf = FakeJellyfin([jf_user("s", "Sarah"), jf_user("n", "nullable.eth")])
        recs = FakeRecs({"n": ["a", "b"], "s": ["c"]})
        run(jf, recs, self.cfg)
        jf.calls.clear()
        result = run(jf, recs, self.cfg)
        self.assertEqual(jf.calls, [])
        self.assertEqual(result.policies_changed, 0)

    def test_failed_fetch_keeps_the_collection(self):
        jf = FakeJellyfin([jf_user("n", "nullable.eth"), jf_user("s", "Sarah")])
        run(jf, FakeRecs({"n": ["a"], "s": ["b"]}), self.cfg)
        result = run(jf, FakeRecs({"s": ["b"]}, failing={"n"}), self.cfg)
        self.assertEqual(len(owned(jf, "n")), 1)
        self.assertEqual(owned(jf, "n")[0]["Members"], ["a"])
        self.assertEqual(len(result.errors), 1)

    def test_empty_for_everyone_is_an_outage_not_a_purge(self):
        # The 2026-10-08 incident: Streamystats answered 200 with no picks for
        # every user (an internal error), and every collection was deleted.
        jf = FakeJellyfin([jf_user("n", "nullable.eth"), jf_user("s", "Sarah")])
        run(jf, FakeRecs({"n": ["a"], "s": ["b"]}), self.cfg)
        result = run(jf, FakeRecs({}), self.cfg)
        self.assertEqual(len(owned(jf, "n")), 1)
        self.assertEqual(len(owned(jf, "s")), 1)
        self.assertEqual(result.removed, 0)
        self.assertEqual(len(result.errors), 1)

    def test_one_user_losing_picks_still_removes_theirs(self):
        jf = FakeJellyfin([jf_user("n", "nullable.eth"), jf_user("s", "Sarah")])
        run(jf, FakeRecs({"n": ["a"], "s": ["b"]}), self.cfg)
        result = run(jf, FakeRecs({"s": ["b"]}), self.cfg)
        self.assertEqual(owned(jf, "n"), [])
        self.assertEqual(result.removed, 1)

    def test_remove_all_undoes_everything_but_hand_set_tags(self):
        jf = FakeJellyfin([jf_user("s", "Sarah", [".no-share"]), jf_user("n", "nullable.eth")])
        run(jf, FakeRecs({"n": ["a"], "s": ["b"]}), self.cfg)
        result = remove_all(jf, self.cfg)
        self.assertEqual(result.removed, 2)
        self.assertEqual(jf.cols, {})
        self.assertEqual(jf._users["s"]["Policy"]["BlockedTags"], [".no-share"])
        self.assertEqual(jf._users["n"]["Policy"]["BlockedTags"], [])


if __name__ == "__main__":
    unittest.main()
