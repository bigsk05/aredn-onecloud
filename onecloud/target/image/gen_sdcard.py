#!/usr/bin/env python3
"""Create the external-media MBR image without mounts or root privileges."""

import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SECTOR = 512
MIB = 1024 * 1024
BOOT_START = 16 * MIB
BOOT_SIZE = 256 * MIB
ROOT_START = BOOT_START + BOOT_SIZE


def create_disk(output, boot, rootfs, signature):
    output, boot, rootfs = map(Path, (output, boot, rootfs))
    if not re.fullmatch(r"[0-9a-fA-F]{8}", signature):
        raise ValueError("An eight-digit MBR signature is required")
    if int(signature, 16) in (0, 0x00002CEB):
        raise ValueError("External media must have a different PARTUUID from eMMC")
    if boot.stat().st_size != BOOT_SIZE:
        raise ValueError("Boot filesystem must be exactly 256 MiB")
    size = rootfs.stat().st_size
    if size < 32 * MIB or size % MIB or ROOT_START + size >= 2**32 * SECTOR:
        raise ValueError("Invalid root filesystem size")
    with rootfs.open("rb") as f:
        f.seek(1024 + 56)
        if f.read(2) != b"\x53\xef":
            raise ValueError("Root filesystem is not ext4")
    mbr = bytearray(SECTOR)
    struct.pack_into("<I", mbr, 440, int(signature, 16))
    for i, (start, length, kind) in enumerate(
        [(BOOT_START, BOOT_SIZE, 0x0E), (ROOT_START, size, 0x83)]
    ):
        struct.pack_into(
            "<B3sB3sII", mbr, 446 + i * 16,
            0x80 if i == 0 else 0, b"\xfe\xff\xff", kind,
            b"\xfe\xff\xff", start // SECTOR, length // SECTOR,
        )
    mbr[510:512] = b"\x55\xaa"
    # OpenWrt's make_ext4fs can leave the padding bits of an inode bitmap
    # unset. Normalize a private copy offline, then demand a clean check.
    # Keep the input untouched because OpenWrt may reuse it for other images.
    with tempfile.TemporaryDirectory(prefix="onecloud-root-", dir=output.parent) as temporary:
        checked_root = Path(temporary) / "rootfs.ext4"
        shutil.copyfile(rootfs, checked_root)
        environment = os.environ.copy()
        if environment.get("SOURCE_DATE_EPOCH"):
            environment["E2FSPROGS_FAKE_TIME"] = environment["SOURCE_DATE_EPOCH"]
        repair = subprocess.run(["e2fsck", "-pf", str(checked_root)], env=environment)
        if repair.returncode not in (0, 1):  # 1 means errors were corrected.
            raise ValueError(f"Root filesystem could not be repaired safely: e2fsck exit {repair.returncode}")
        subprocess.run(["e2fsck", "-fn", str(checked_root)], env=environment, check=True)
        with output.open("wb") as dest:
            dest.write(mbr)
            dest.seek(BOOT_START)
            with boot.open("rb") as source:
                shutil.copyfileobj(source, dest, 1024 * 1024)
            dest.seek(ROOT_START)
            with checked_root.open("rb") as source:
                shutil.copyfileobj(source, dest, 1024 * 1024)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit("Usage: gen_sdcard.py OUTPUT BOOT.FAT ROOTFS.EXT4 MBR_SIGNATURE")
    create_disk(*sys.argv[1:])
