#!/usr/bin/env python3
"""Fetch the verified OneCloud bootloader and build the pinned burn packer."""

import argparse
import json
from pathlib import Path
import subprocess

from images import read_burn, sha256
from prepare import LOCK, checkout, git, run
from validate import require


def prepare_bootloader(destination):
    destination.mkdir(parents=True, exist_ok=True)
    burn = destination / "u-boot.burn.img"
    if not burn.exists():
        partial = destination / "u-boot.burn.img.part"
        run("curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "20",
            "--max-time", "300", "--output", str(partial), LOCK["uboot"]["url"])
        require(sha256(partial) == LOCK["uboot"]["sha256"], "U-Boot download checksum mismatch")
        partial.replace(burn)
    require(sha256(burn) == LOCK["uboot"]["sha256"], "Cached U-Boot checksum mismatch")
    read_burn(burn)
    source = destination / "AmlImg-source"
    if not source.exists():
        checkout(LOCK["amlimg"]["url"], LOCK["amlimg"]["commit"], source)
    require(git("rev-parse", "HEAD", cwd=source) == LOCK["amlimg"]["commit"], "Wrong AmlImg revision")
    require(not git("status", "--porcelain", cwd=source), "AmlImg source is not clean")
    run("env", "CGO_ENABLED=0", "GOTOOLCHAIN=local", "GOPROXY=off",
        "go", "build", "-trimpath", "-buildvcs=false", "-o", str(destination / "AmlImg"), ".", cwd=source)
    (destination / "sources.json").write_text(json.dumps({k: LOCK[k] for k in ("uboot", "amlimg")}, indent=2) + "\n")
    print(f"Verified OneCloud U-Boot and built AmlImg in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        prepare_bootloader(args.destination.resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Bootloader preparation failed: {error}\n")
