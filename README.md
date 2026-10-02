# dopehub-coming-soon

Coming-soon site for DopeHub.net: cinematic background loops, newsletter and beta sign-up, and join-the-team applications.

- `site/` the page (`index.html`, `site.css`, `site.js`), form logic (`app.js`), fonts, admin and the processed loops in `site/media/loops/`.
- `server/` sign-up and application service (Python, SQLite). `server/env.example` lists the settings.
- `tools/preview.py` local preview that never sends email: `python3 tools/preview.py`, then open http://127.0.0.1:8775/ (email previews at `/__mail/`).
- `make-loops.sh` turns a source clip into a seamless, silent loop (WebM, MP4, poster).
- `guide1.pdf`, `guide2.pdf` the engineering and design guides the page follows.
- `ComingSoonDopeHub.net*.zip` the earlier attempts, kept for reference.

Phones under 768px, reduced-motion and data-saver visitors get the still poster instead of the video. A Pause motion button is shown wherever video plays.
