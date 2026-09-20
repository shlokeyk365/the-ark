#!/usr/bin/env bash
#
# Extract the Kantipur-valley basemap from the Protomaps daily planet build.
#
# Produces a single PMTiles archive that the dashboard serves as a static file.
# No account, API key, or tile server is involved. The extract pulls only the
# tiles inside the bounding box over HTTP range requests, so it transfers ~20 MB
# rather than the 138 GB planet.
#
# Usage:  ./scripts/fetch-basemap.sh [YYYYMMDD]
#         FORCE=1 ./scripts/fetch-basemap.sh   # refresh even if the archive exists
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BBOX="85.20,27.55,85.45,27.82"   # Kantipur scenario + admin context + panning room
MAXZOOM=15
OUT="$REPO_ROOT/apps/web/public/basemap/kantipur.pmtiles"
PMTILES_VERSION="1.31.2"

if [ "${FORCE:-0}" != "1" ] && [ -s "$OUT" ]; then
  echo "exists: $OUT ($(du -h "$OUT" | cut -f1)); set FORCE=1 to refresh"
  exit 0
fi

probe_build() {
  # Range GET, not HEAD: some CDNs (including Cloudflare from CI IPs) 403 HEAD.
  curl -sf -r 0-15 -o /dev/null "$1"
}

# Protomaps keeps roughly two weeks of daily builds.
BUILD="${1:-}"
if [ -z "$BUILD" ]; then
  for offset in 1 2 3 4 5 6 7; do
    candidate=""
    if candidate=$(date -u -d "${offset} days ago" +%Y%m%d 2>/dev/null); then
      :
    elif candidate=$(date -u -v-"${offset}"d +%Y%m%d 2>/dev/null); then
      :
    else
      continue
    fi
    if probe_build "https://build.protomaps.com/${candidate}.pmtiles"; then
      BUILD="$candidate"
      break
    fi
  done
fi

if [ -z "$BUILD" ]; then
  echo "error: could not find a recent Protomaps daily build" >&2
  exit 1
fi

SOURCE="https://build.protomaps.com/${BUILD}.pmtiles"
echo "source : $SOURCE"
echo "bbox   : $BBOX (maxzoom $MAXZOOM)"
echo "output : $OUT"

# Prefer a pmtiles CLI on PATH; otherwise fetch the pinned release into a cache.
if command -v pmtiles >/dev/null 2>&1; then
  PMTILES_BIN="$(command -v pmtiles)"
else
  CACHE="${TMPDIR:-/tmp}/the-ark-pmtiles-${PMTILES_VERSION}"
  PMTILES_BIN="$CACHE/pmtiles"
  if [ ! -x "$PMTILES_BIN" ]; then
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64)  ASSET="go-pmtiles-${PMTILES_VERSION}_Darwin_arm64.zip" ;;
      Darwin-x86_64) ASSET="go-pmtiles-${PMTILES_VERSION}_Darwin_x86_64.zip" ;;
      Linux-aarch64) ASSET="go-pmtiles-${PMTILES_VERSION}_Linux_arm64.tar.gz" ;;
      Linux-x86_64)  ASSET="go-pmtiles-${PMTILES_VERSION}_Linux_x86_64.tar.gz" ;;
      *) echo "error: install the pmtiles CLI manually for $(uname -s)-$(uname -m)" >&2; exit 1 ;;
    esac
    echo "fetching pmtiles CLI $PMTILES_VERSION…"
    mkdir -p "$CACHE"
    URL="https://github.com/protomaps/go-pmtiles/releases/download/v${PMTILES_VERSION}/${ASSET}"
    case "$ASSET" in
      *.zip)    curl -sL "$URL" -o "$CACHE/pmtiles.zip" && unzip -oq "$CACHE/pmtiles.zip" -d "$CACHE" ;;
      *.tar.gz) curl -sL "$URL" | tar -xz -C "$CACHE" ;;
    esac
    chmod +x "$PMTILES_BIN"
  fi
fi

mkdir -p "$(dirname "$OUT")"
"$PMTILES_BIN" extract "$SOURCE" "$OUT" --bbox="$BBOX" --maxzoom="$MAXZOOM"

echo
echo "done: $(du -h "$OUT" | cut -f1) at $OUT"
