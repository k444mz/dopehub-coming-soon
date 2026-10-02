# DopeHub.net coming-soon site: project notes

Read this first. It records what exists, what was decided, and what is still open.

## What is here
- `source-videos/video1..5.mp4`: the five original 10 s, 1280x720, 24 fps clips (each has a silent audio track).
  - video1 neon grow room (pink/cyan; reads commercial, not recommended)
  - video2 sunset behind a cannabis plant silhouette, amber haze, almost static camera: **best hero loop**
  - video3 golden-hour close-up of leaves, sun behind: good second scene
  - video4 misty pine forest with raised beds, camera moves forward: usable as a section background
  - video5 bright glass greenhouse, camera moves forward: **the current hero** (Kam's choice, 2 October 2026). It is graded
    darker and sits under a scrim; its last frames return to its first, so it loops with a hard cut and no crossfade
- `site/media/loops/<name>.{webm,mp4,-poster.webp}`: processed loops made by `make-loops.sh`
  (1920x1080, 24 fps, 8.5 s, silent, last 1.5 s crossfaded into the start so the loop has no visible join).
  hero-sunset = video2, join-golden-hour = video3, community-forest = video4, grow-room-neon = video1, greenhouse = video5.
  Re-run `./make-loops.sh <source.mp4> <name> [brightness contrast saturation]` for a new clip; it needs ffmpeg.
  The greenhouse loop is different: 1280x720 (the source's native size), 9.92 s, emerald grade, 2.6 MB MP4 / 2.8 MB WebM. Rebuild it with:
  `CUT_FRAMES=238 SHARP=0 SIZE=1280:720 GRADE="hqdn3d=3:3:9:9,curves=r='0/0 0.3/0.21 0.7/0.6 1/0.8':g='0/0.01 0.3/0.25 0.7/0.67 1/0.88':b='0/0.02 0.3/0.24 0.7/0.62 1/0.82'" CRF_MP4=30 CRF_WEBM=45 ./make-loops.sh source-videos/video5.mp4 greenhouse 0 1.14 1.28`
- `guide1.pdf` (engineering: strip audio, WebM + MP4 under ~3.5 MB, poster image, gradient scrim, reduced-motion,
  poster only on phones under 768 px) and `guide2.pdf` (design: three layers, film grain, mouse parallax, glass invite form).
- `site/`: the page (`index.html`, `site.css`, `site.js`), dialogs and application logic (`app.js`), self-hosted fonts, admin panel, logo, `og.jpg` (rendered from the hero).
  Page order: hero (greenhouse loop, headline, countdown) → values ticker → Subscribe for updates (glass box over the video) →
  Beta invitation (obsidian section, floating invitation card with steps) → Join the team (the `join-section` / `.contributions` structure
  from the earlier attempts, now inline in a glass panel) → footer. Dialogs: team application, privacy, unsubscribe.
  Glass panels are `.lux` (frosted backdrop, travelling conic border, inner bevel, cursor tilt and spotlight from `site.js`).
- `server/signup_service.py`: the Python/SQLite backend from the earlier attempts. Endpoints the page uses:
  `POST /api/subscribe` {email, newsletter, beta, consent, website(honeypot)}, `POST /api/apply` (team application),
  `POST /api/confirm`, `POST /api/unsubscribe`, `POST /api/hit`. Double opt-in by email. `server/env.example` lists settings.
- `tools/preview.py`: local preview on http://127.0.0.1:8775/ that writes emails to `preview/local/emails/` and never sends.
- `tests/`: `python3 -m unittest discover -s tests` (12 tests, one skipped: its fixture is not in this repo).
- `ComingSoonDopeHub.net*.zip`: the two earlier attempts, kept for reference only.

## Decisions so far
- Scripts and styles must be self-hosted: the preview server and production config send a CSP of `script-src 'self'; style-src 'self'`.
  No Tailwind CDN, no Google Fonts links. Fonts in use, downloaded from Google Fonts and self-hosted (all SIL OFL, licences in `site/fonts/`):
  Archivo Expanded (Archivo variable pinned to width 125, weights 400-800; headings), Space Grotesk (body), Instrument Serif Italic (accent words),
  Manrope (logo only). Clash Display / Satoshi were requested but fontshare.com is still blocked from the build environment; add a .woff2 to `site/fonts/` to use one.
- Video is only loaded on screens 768 px and wider, with reduced-motion off and no data-saver; everyone else gets the poster.
  A visible Pause motion button shows wherever video plays.
- Forms reuse the backend above; do not invent a new signup store. Consent (18+) is required by the server.
  The updates form posts `{newsletter: true, beta: false}`; the beta card posts `{beta: true, newsletter: <its checkbox>}`.
- The countdown's launch moment is `data-launch` on `.countdown` in `site/index.html`; it is a placeholder (1 Dec 2026 09:00 UTC) until Kam gives the real date.
- Headline (Kam's choice, 2 October 2026): "Grown by the community, for the community." with the supporting line
  "Independent. Moderated. Built on lived experience." Do not use "Out of the haze".
- Community-first wording: members, community, lived experience. Never "patients" except as the precise medical/legal term.
  No prices, sellers, stock or purchase links. Not medical advice. UK, 18+.
- Commits use Kam's identity; no assistant credit lines in the repo.

## Still open
- OpenRouter (optional, for regenerating or upscaling the hero footage): the first key was pasted into a chat and must be revoked.
  A new key goes in the environment variable `OPENROUTER_API_KEY` and `openrouter.ai` must be allowed in the environment's network settings.
- Portrait phone loops and deployment are not done.
