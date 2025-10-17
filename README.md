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
```

## Configuration

1. Create a `.env` file in the project root:

   ```env
   JELLYFIN_BASE_URL=https://your-jellyfin.example.com
   JELLYFIN_API_KEY=replace-with-your-api-key
   ```

2. Restart the Flask app (or `docker compose up --build -d`) so the environment variables are loaded.

When the app starts, the values from `.env` will be pre-filled in the UI to save you from retyping them.
