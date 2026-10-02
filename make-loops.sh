#!/usr/bin/env bash
# Turns a source clip into a seamless, silent background loop (WebM + MP4 + poster) in site/media/loops/.
# Usage: ./make-loops.sh <source.mp4> <name> [brightness contrast saturation]
# Optional environment:
#   GRADE       extra ffmpeg filters after eq, e.g. hqdn3d or curves (default none)
#   SIZE        output size (default 1920:1080)      SHARP     unsharp amount (default 0.4)
#   CRF_MP4     H.264 quality (default 27)           CRF_WEBM  VP9 quality (default 37)
#   CUT_FRAMES  for clips whose last frames return to the first: keep this many frames and cut
#               straight back to frame 0 instead of crossfading the last 1.5 s into the start
set -euo pipefail
SRC="$1"; NAME="$2"; BRIGHT="${3:--0.05}"; CONTRAST="${4:-1.08}"; SAT="${5:-1.05}"
SHARP="${SHARP:-0.4}"; GRADE="${GRADE:-null}"; SIZE="${SIZE:-1920:1080}"; CRF_MP4="${CRF_MP4:-27}"; CRF_WEBM="${CRF_WEBM:-37}"
CUT_FRAMES="${CUT_FRAMES:-}"
OUT="$(dirname "$0")/site/media/loops"; X=1.5            # crossfade seconds
LOOK="scale=${SIZE}:flags=lanczos,unsharp=5:5:${SHARP},eq=brightness=${BRIGHT}:contrast=${CONTRAST}:saturation=${SAT},${GRADE},fps=24"
if [ -n "$CUT_FRAMES" ]; then
  FILTER="[0:v]trim=end_frame=${CUT_FRAMES},setpts=PTS-STARTPTS,${LOOK},format=yuv420p[v]"
else
  D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
  MID_END=$(echo "$D - $X" | bc -l); TAIL_START="$MID_END"
  FILTER="[0:v]${LOOK},split=3[a][b][c];
[a]trim=0:${X},setpts=PTS-STARTPTS[head];
[b]trim=${X}:${MID_END},setpts=PTS-STARTPTS[mid];
[c]trim=${TAIL_START}:${D},setpts=PTS-STARTPTS[tail];
[tail][head]xfade=transition=fade:duration=${X}:offset=0[blend];
[blend][mid]concat=n=2:v=1:a=0,format=yuv420p[v]"
fi
ffmpeg -v error -y -i "$SRC" -filter_complex "$FILTER" -map "[v]" -an -c:v libx264 -preset slow -crf "$CRF_MP4" -movflags +faststart "$OUT/$NAME.mp4"
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -c:v libvpx-vp9 -b:v 0 -crf "$CRF_WEBM" -row-mt 1 -deadline good -cpu-used 1 -an "$OUT/$NAME.webm"
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -vframes 1 -c:v libwebp -quality 80 "$OUT/$NAME-poster.webp"
echo "$NAME: $(du -h "$OUT/$NAME.mp4" | cut -f1) mp4, $(du -h "$OUT/$NAME.webm" | cut -f1) webm, $(du -h "$OUT/$NAME-poster.webp" | cut -f1) poster"
