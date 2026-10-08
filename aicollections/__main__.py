"""Run one reconciliation pass (meant for a CronJob), or `--remove` to undo.

Environment:
  JELLYFIN_URL            e.g. http://jellyfin:8096
  JELLYFIN_API_KEY        admin API key (also used for Streamystats)
  STREAMYSTATS_URL        e.g. http://streamystats-web:3001
  COLLECTION_NAME         default "AI Recommendations"
  COLLECTION_SIZE         default 30
  HIDE_TAG_PREFIX         default ".hide-from-"
"""

from __future__ import annotations

import logging
import os
import sys

from .jellyfin import Jellyfin
from .streamystats import Streamystats
from .sync import Config, remove_all, run


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("aicollections")
    try:
        jf = Jellyfin(os.environ["JELLYFIN_URL"], os.environ["JELLYFIN_API_KEY"])
        cfg = Config(
            display_name=os.environ.get("COLLECTION_NAME", "AI Recommendations"),
            size=int(os.environ.get("COLLECTION_SIZE", "30")),
            tag_prefix=os.environ.get("HIDE_TAG_PREFIX", ".hide-from-"),
        )
    except KeyError as e:
        log.error("missing environment variable %s", e)
        return 2

    if "--remove" in argv:
        result = remove_all(jf, cfg)
    else:
        recs = Streamystats(
            os.environ["STREAMYSTATS_URL"], jf.api_key, jf.server_id()
        )
        result = run(jf, recs, cfg)

    log.info(
        "action=%s collections=%d removed=%d policiesChanged=%d errors=%d",
        "remove" if "--remove" in argv else "sync",
        result.collections, result.removed, result.policies_changed, len(result.errors),
    )
    for err in result.errors:
        log.error("%s", err)
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
