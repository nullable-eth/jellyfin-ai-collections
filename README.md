# jellyfin-ai-collections

Gives every Jellyfin user a private **"AI Recommendations"** collection, filled
from [Streamystats](https://github.com/fredrikburmester/streamystats)
recommendations and refreshed on a schedule, with a 2×2 poster collage cover.

## Privacy

Jellyfin has no per-collection permissions, but parental-control *blocked tags*
apply to collections. Each user's collection is tagged `.hide-from-<user>` for
every other user, and each user's policy blocks only their own
`.hide-from-<self>` tag. That is one blocked tag per user, maintained here: new
users and renames are handled on the next run. Other blocked tags are left
untouched.

- New collections are created empty and hidden before anything is added, and
  deleted again if hiding fails.
- A newly created Jellyfin user can see other users' collections until the next
  run tags them out, so run it often (e.g. every 15 minutes).
- Owners can see the hide tags on their own collection (the other user names).

Ownership and the current cover are stored as provider ids on the collection
itself (`AiRecommendationsUser`, `AiRecommendationsCover`), so the service is
stateless.

## Running

One pass per invocation; run it as a cron job:

```
python -m aicollections            # sync
python -m aicollections --remove   # delete the collections and our blocked tags
```

| Variable | Default | |
|---|---|---|
| `JELLYFIN_URL` | — | e.g. `http://jellyfin:8096` |
| `JELLYFIN_API_KEY` | — | Jellyfin admin API key (also used for Streamystats) |
| `STREAMYSTATS_URL` | — | e.g. `http://streamystats:3000` |
| `COLLECTION_NAME` | `AI Recommendations` | |
| `COLLECTION_SIZE` | `30` | |
| `HIDE_TAG_PREFIX` | `.hide-from-` | |

Recommendations come from Streamystats' `/api/recommendations` with
`targetUserId`, so each user's own Streamystats settings and library access
apply.

## Tests

```
pip install pillow
python -m unittest discover -s tests
```
