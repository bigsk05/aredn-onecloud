#!/usr/bin/env bash
# Compile the official AREDN packages and the native OneCloud kernel together.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 || ( $# == 2 && $2 != --prepare-only ) ]]; then
    echo "Usage: $0 PREPARED_SOURCE [--prepare-only]" >&2
    exit 2
fi
port_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=$(realpath -- "$1")
cd -- "$source_dir"
mapfile -t spec < <(python3 - <<'PY'
import json
from pathlib import Path
p = json.loads(Path('onecloud-build.json').read_text())
for value in (p['version'], p['sources']['openwrt']['commit'], p['source_date_epoch'], p['sources']['aredn']['commit']):
    print(value)
PY
)
[[ ${#spec[@]} == 4 ]] || { echo 'Missing source plan' >&2; exit 1; }
[[ $(git rev-parse HEAD) == "${spec[3]}" ]] || { echo 'Wrong AREDN revision' >&2; exit 1; }
[[ $(git -C openwrt rev-parse HEAD) == "${spec[1]}" ]] || { echo 'Wrong OpenWrt revision' >&2; exit 1; }
jobs=${ONECLOUD_JOBS:-$(nproc)}
[[ $jobs =~ ^[1-9][0-9]*$ ]] || { echo 'Invalid ONECLOUD_JOBS' >&2; exit 2; }
if [[ -z ${ONECLOUD_JOBS:-} && $jobs -gt 8 ]]; then jobs=8; fi
export SOURCE_DATE_EPOCH=${spec[2]}
args=("TARGET=amlogic-meson8b" "OPENWRT_COMMIT=${spec[1]}" "FW_VERSION=${spec[0]}"
      "PRIVATE_BUILD_PACKAGES=/opt/aredn-packages")
if [[ -n ${ONECLOUD_DL_DIR:-} ]]; then
    mkdir -p -- "$ONECLOUD_DL_DIR"
    args+=("DL_DIR=$(realpath -- "$ONECLOUD_DL_DIR")")
fi
if [[ -n ${ONECLOUD_CCACHE_DIR:-} ]]; then
    mkdir -p -- "$ONECLOUD_CCACHE_DIR"
    args+=("CCACHE_DIR=$(realpath -- "$ONECLOUD_CCACHE_DIR")")
fi
make "${args[@]}" prepare
python3 "$port_dir/scripts/validate.py" config "$source_dir"
[[ ${2:-} != --prepare-only ]] || exit 0
make -C openwrt "${args[@]}" -j"$jobs" download
# Call OpenWrt directly: upstream AREDN's final cleanup removes image types
# belonging to targets it does not officially support.
make -C openwrt "${args[@]}" -j"$jobs" V=s BUILD_LOG=1
python3 "$port_dir/scripts/validate.py" build "$source_dir"
