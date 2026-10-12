#!/usr/bin/env python3
"""Independent structural checks for OneCloud disk and Amlogic burn images."""

import hashlib
from pathlib import Path
import re
import struct
import zlib

from validate import require

MIB = 1024 * 1024
BOOT_START = 16 * MIB
BOOT_SIZE = 256 * MIB
ROOT_START = BOOT_START + BOOT_SIZE


def sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read_exact(source, count):
    data = source.read(count)
    require(len(data) == count, "Truncated image")
    return data


def copy_region(source, offset, size, destination):
    with Path(source).open("rb") as src, Path(destination).open("wb") as dst:
        src.seek(offset)
        while size:
            data = read_exact(src, min(size, MIB))
            dst.write(data)
            size -= len(data)


def check_ext4(source, offset, available):
    source.seek(offset + 1024)
    sb = read_exact(source, 1024)
    require(sb[56:58] == b"\x53\xef", "Missing ext4 superblock")
    log_block_size = struct.unpack_from("<I", sb, 24)[0]
    require(log_block_size <= 6, "Invalid ext4 block size")
    block_size = 1024 << log_block_size
    blocks = struct.unpack_from("<I", sb, 4)[0]
    if struct.unpack_from("<I", sb, 96)[0] & 0x80:
        blocks |= struct.unpack_from("<I", sb, 336)[0] << 32
    require(0 < blocks * block_size <= available, "ext4 filesystem exceeds its partition")


def check_disk(path):
    path = Path(path)
    size = path.stat().st_size
    require(size % 512 == 0, "Disk must contain complete sectors")
    with path.open("rb") as source:
        mbr = read_exact(source, 512)
        require(mbr[510:] == b"\x55\xaa", "Missing DOS/MBR signature")
        signature = f"{struct.unpack_from('<I', mbr, 440)[0]:08x}"
        require(signature not in ("00000000", "00002ceb"), "External disk has an ambiguous PARTUUID")
        partitions = []
        for index in range(2):
            active, _, kind, _, start, length = struct.unpack_from("<B3sB3sII", mbr, 446 + 16 * index)
            require(active in (0, 0x80), "Invalid MBR active flag")
            partitions.append({"start": start * 512, "size": length * 512, "type": kind})
        boot, root = partitions
        require(boot == {"start": BOOT_START, "size": BOOT_SIZE, "type": 0x0E}, "Wrong FAT16 partition layout")
        require(root["start"] == ROOT_START and root["type"] == 0x83, "Wrong root partition layout")
        require(root["size"] >= 32 * MIB and root["start"] + root["size"] == size, "Root partition does not fit the image")
        require(mbr[478:510] == b"\0" * 32, "Unexpected extra partitions")
        source.seek(BOOT_START)
        fat = read_exact(source, 512)
        require(fat[510:] == b"\x55\xaa" and fat[54:62] == b"FAT16   ", "Boot filesystem is not FAT16")
        require(struct.unpack_from("<H", fat, 11)[0] == 512, "Unexpected FAT sector size")
        check_ext4(source, root["start"], root["size"])
    return {"signature": signature, "boot": boot, "root": root}


def check_uimage(path, image_type=2):
    data = Path(path).read_bytes()
    require(len(data) >= 64, "Truncated uImage")
    fields = struct.unpack_from(">7I4B32s", data)
    magic, header_crc, _, size, load, entry, data_crc, os_id, arch, kind, compression, _ = fields
    require(magic == 0x27051956, "Missing legacy U-Boot image header")
    header = data[:4] + b"\0" * 4 + data[8:64]
    require(zlib.crc32(header) == header_crc, "uImage header checksum mismatch")
    require(size == len(data) - 64 and zlib.crc32(data[64:]) == data_crc, "uImage data checksum mismatch")
    require((os_id, arch, kind, compression) == (5, 2, image_type, 0), "Wrong U-Boot image type/architecture")
    if image_type == 2:
        require(load == entry == 0x00208000, "Wrong S805 kernel load/entry address")
        require(len(data) < 16 * MIB, "Kernel load would overlap the DTB at 0x21800000")
    return data[64:]


def sparse_size(source, offset, length):
    source.seek(offset)
    magic, major, minor, header_size, chunk_size, block_size, blocks, chunks, _ = struct.unpack(
        "<I4H4I", read_exact(source, 28)
    )
    require((magic, major, minor) == (0xED26FF3A, 1, 0), "Invalid Android sparse header")
    require(header_size == 28 and chunk_size == 12 and block_size == 4096, "Unexpected sparse geometry")
    require(0 < chunks <= 1000000 and blocks > 0, "Invalid sparse chunk count")
    used, expanded = 28, 0
    for _ in range(chunks):
        require(used + 12 <= length, "Truncated sparse chunk")
        kind, _, count, size = struct.unpack("<2H2I", read_exact(source, 12))
        expected = {0xCAC1: count * block_size, 0xCAC2: 4, 0xCAC3: 0, 0xCAC4: 4}.get(kind)
        require(expected is not None and size == 12 + expected, "Invalid sparse chunk size/type")
        require(used + size <= length, "Sparse chunk exceeds its container")
        require(kind != 0xCAC4 or count == 0, "Invalid sparse CRC chunk")
        source.seek(expected, 1)
        used += size
        expanded += count
    require(used == length and expanded == blocks, "Sparse image length mismatch")
    return blocks * block_size


def read_burn(path):
    """Validate the container CRC, extents, SHA-1 records and sparse geometry."""
    path = Path(path)
    with path.open("rb") as source:
        header = read_exact(source, 64)
        crc, version, magic, size, alignment, count = struct.unpack_from("<IIIQII", header)
        require((version, magic, alignment) == (2, 0x27B51956, 4), "Not an Amlogic v2 burn image")
        require(size == path.stat().st_size and 0 < count <= 32, "Invalid burn image size/item count")
        source.seek(4)
        running = 0
        while block := source.read(MIB):
            running = zlib.crc32(block, running)
        # Amlogic stores the uncomplemented CRC state, unlike standard CRC32.
        require((running ^ 0xFFFFFFFF) == crc, "Amlogic container CRC mismatch")
        source.seek(64)
        items = {}
        previous_end = 64 + 576 * count
        for index in range(count):
            raw = read_exact(source, 576)
            ident, kind, item_offset, offset, length = struct.unpack_from("<IIQQQ", raw)
            main = raw[32:288].split(b"\0", 1)[0].decode("ascii")
            sub = raw[288:544].split(b"\0", 1)[0].decode("ascii")
            require(re.fullmatch(r"[a-zA-Z0-9_]+", main) and re.fullmatch(r"[a-zA-Z0-9_]+", sub), "Invalid item name")
            require(ident == index and kind in (0, 0xFE) and item_offset == 0, "Invalid item header")
            require(offset % 4 == 0 and previous_end <= offset and length > 0 and offset + length <= size, "Overlapping/out-of-bounds burn item")
            require((main, sub) not in items, "Duplicate burn item")
            items[(main, sub)] = {"offset": offset, "size": length, "type": kind}
            previous_end = offset + length
        for key, item in items.items():
            source.seek(item["offset"])
            remaining = item["size"]
            sha1, digest = hashlib.sha1(), hashlib.sha256()
            while remaining:
                block = read_exact(source, min(remaining, MIB))
                sha1.update(block)
                digest.update(block)
                remaining -= len(block)
            item["sha256"] = digest.hexdigest()
            if key[0] == "PARTITION":
                verify = items.get(("VERIFY", key[1]))
                require(verify and verify["size"] == 48, "Missing partition verification record")
                source.seek(verify["offset"])
                require(read_exact(source, 48) == ("sha1sum " + sha1.hexdigest()).encode(), "Partition SHA-1 mismatch")
            if item["type"] == 0xFE:
                item["expanded_size"] = sparse_size(source, item["offset"], item["size"])
    return items


def check_burn(path, base, root_size):
    expected = read_burn(base)
    items = read_burn(path)
    require(set(items) == set(expected) | {("PARTITION", "boot"), ("VERIFY", "boot"), ("PARTITION", "rootfs"), ("VERIFY", "rootfs")}, "Unexpected burn image contents")
    for key, original in expected.items():
        for field in ("size", "type", "sha256"):
            require(items[key][field] == original[field], f"Bootloader component was modified: {key}")
    require(items[("PARTITION", "boot")].get("expanded_size") == BOOT_SIZE, "Wrong eMMC boot partition size")
    require(items[("PARTITION", "rootfs")].get("expanded_size") == root_size, "Wrong eMMC root filesystem size")
    return items
