#!/usr/bin/env bash
# Turns a source clip into a seamless, silent background loop (WebM + MP4 + poster).
# Usage: ./make-loops.sh <source.mp4> <name> <brightness> <contrast> <saturation>
set -euo pipefail
SRC="$1"; NAME="$2"; BRIGHT="${3:--0.05}"; CONTRAST="${4:-1.08}"; SAT="${5:-1.05}"
OUT="$(dirname "$0")/media/loops"; X=1.5            # crossfade seconds
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
MID_END=$(echo "$D - $X" | bc -l); TAIL_START="$MID_END"
FILTER="[0:v]scale=1920:1080:flags=lanczos,unsharp=5:5:0.4,eq=brightness=${BRIGHT}:contrast=${CONTRAST}:saturation=${SAT},fps=24,split=3[a][b][c];
[a]trim=0:${X},setpts=PTS-STARTPTS[head];
[b]trim=${X}:${MID_END},setpts=PTS-STARTPTS[mid];
[c]trim=${TAIL_START}:${D},setpts=PTS-STARTPTS[tail];
[tail][head]xfade=transition=fade:duration=${X}:offset=0[blend];
[blend][mid]concat=n=2:v=1:a=0,format=yuv420p[v]"
ffmpeg -v error -y -i "$SRC" -filter_complex "$FILTER" -map "[v]" -an -c:v libx264 -preset slow -crf 27 -movflags +faststart "$OUT/$NAME.mp4"
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -c:v libvpx-vp9 -b:v 0 -crf 37 -row-mt 1 -deadline good -cpu-used 1 -an "$OUT/$NAME.webm"
ffmpeg -v error -y -i "$OUT/$NAME.mp4" -vframes 1 -c:v libwebp -quality 80 "$OUT/$NAME-poster.webp"
echo "$NAME: $(du -h "$OUT/$NAME.mp4" | cut -f1) mp4, $(du -h "$OUT/$NAME.webm" | cut -f1) webm, $(du -h "$OUT/$NAME-poster.webp" | cut -f1) poster"
