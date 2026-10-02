# DopeHub.net coming-soon site: project notes

Read this first. It records what exists, what was decided, and what is still open.

## What is here
- `source-videos/video1..5.mp4`: the five original 10 s, 1280x720, 24 fps clips (each has a silent audio track).
  - video1 neon grow room (pink/cyan; reads commercial, not recommended)
  - video2 sunset behind a cannabis plant silhouette, amber haze, almost static camera: **best hero loop**
  - video3 golden-hour close-up of leaves, sun behind: good second scene
  - video4 misty pine forest with raised beds, camera moves forward: usable as a section background
  - video5 bright glass greenhouse, camera moves forward: too bright for text, not recommended
- `site/media/loops/<name>.{webm,mp4,-poster.webp}`: processed loops made by `make-loops.sh`
  (1920x1080, 24 fps, 8.5 s, silent, last 1.5 s crossfaded into the start so the loop has no visible join).
  hero-sunset = video2, join-golden-hour = video3, community-forest = video4, grow-room-neon = video1, greenhouse = video5.
  Re-run `./make-loops.sh <source.mp4> <name> [brightness contrast saturation]` for a new clip; it needs ffmpeg.
- `guide1.pdf` (engineering: strip audio, WebM + MP4 under ~3.5 MB, poster image, gradient scrim, reduced-motion,
  poster only on phones under 768 px) and `guide2.pdf` (design: three layers, film grain, mouse parallax, glass invite form).
- `site/`: the page (`index.html`, `site.css`, `site.js`), form logic (`app.js`), self-hosted fonts, admin panel, logo.
- `server/signup_service.py`: the Python/SQLite backend from the earlier attempts. Endpoints the page uses:
  `POST /api/subscribe` {email, newsletter, beta, consent, website(honeypot)}, `POST /api/apply` (team application),
  `POST /api/confirm`, `POST /api/unsubscribe`, `POST /api/hit`. Double opt-in by email. `server/env.example` lists settings.
- `tools/preview.py`: local preview on http://127.0.0.1:8775/ that writes emails to `preview/local/emails/` and never sends.
- `tests/`: `python3 -m unittest discover -s tests` (12 tests, one skipped: its fixture is not in this repo).
- `ComingSoonDopeHub.net*.zip`: the two earlier attempts, kept for reference only.

## Decisions so far
- Scripts and styles must be self-hosted: the preview server and production config send a CSP of `script-src 'self'; style-src 'self'`.
  No Tailwind CDN, no Google Fonts links. Fonts in use: Gambetta (serif display), Switzer (sans), Manrope (logo only).
  Clash Display / Plus Jakarta Sans were requested but fontshare.com is unreachable from the build environment; add a .woff2 to `site/fonts/` to use one.
- Video is only loaded on screens 768 px and wider, with reduced-motion off and no data-saver; everyone else gets the poster.
  A visible Pause motion button shows wherever video plays.
- Forms reuse the backend above; do not invent a new signup store. Consent (18+) is required by the server.
- No countdown timer (Kam, 2 October 2026). The hero is conversion-only: early-access bar (newsletter via `/api/subscribe`), beta-invite sheet (`#signup-dialog`, beta pre-selected) and join-the-team (`#contribute` then `#apply`).
- Hero layering: video2 loop, then `.warmth` (amber soft-light undertone), `.scrim` (left-to-right directional, top-to-bottom on phones), `.vignette`, `.bloom` on the sun, `.film-grain`. Text sits on the left over the darkest part of the frame.
- Box language (Kam asked for less generic boxes, 2 October 2026): `.frame` = frosted pane with an inset passe-partout line, `.ticks` amber corner marks that open out on hover/focus, `.sweep` light travelling the border; small radii and uppercase tracked buttons. Secondary choices and the about pillars are open ruled entries (top hairline that fills amber on hover), not cards. No decorative numbering (N° 01, 01/02/03) or filler tags like "Double opt-in": Kam removed them as generic.
- Markup must not use `style=""` attributes (blocked by the CSP); use classes. `site.js` exposes `window.dhToast(text)` for success toasts.
- Headline (Kam's choice, 2 October 2026): "Grown by the community, for the community." with the supporting line
  "Independent. Moderated. Built on lived experience." Do not use "Out of the haze".
- Community-first wording: members, community, lived experience. Never "patients" except as the precise medical/legal term.
  No prices, sellers, stock or purchase links. Not medical advice. UK, 18+.
- Commits use Kam's identity; no assistant credit lines in the repo.

## Still open
- OpenRouter (optional, for regenerating or upscaling the hero footage): the first key was pasted into a chat and must be revoked.
  A new key goes in the environment variable `OPENROUTER_API_KEY` and `openrouter.ai` must be allowed in the environment's network settings.
- Portrait phone loops and deployment are not done.
