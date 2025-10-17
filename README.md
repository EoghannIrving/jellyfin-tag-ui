# Jellyfin Tag UI

A Dockerized Flask web UI to **filter by include/exclude tags** within a single Jellyfin library and **bulk apply tag changes**.

## Features
- Select **User** and **Library**
- Filter by **Include Tags** and/or **Exclude Tags**
- List matching items with current tags
- **Bulk add/remove** tags for selected items
- **Export CSV** of items and tags
- Robust tag listing:
  - Tries `/Users/{userId}/Items/Tags`
  - Falls back to `/Items/Tags`
  - Aggregates from `TagItems` if needed

## Quick start
```bash
docker compose up --build -d
# open http://localhost:8088
