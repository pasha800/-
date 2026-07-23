# Media Download Fix v1.3.2

- Wikimedia SVG/GIF links are resolved to valid PNG/JPEG/WebP thumbnails.
- HTTP 400 candidates fall back to alternate valid thumbnail widths.
- HTTP 429 responses use host cooldown and persistent exponential backoff.
- A failed media URL is not requested again for every match.
- Each team/player is attempted at most once in one process run.
- Permanent invalid URLs are cached until the provider supplies a changed URL.
- Images remain external files; SQLite stores only local links and compact retry state.
