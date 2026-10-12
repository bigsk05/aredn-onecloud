"""Exercise real filesystem/boot tools; no loop devices or mounts are needed."""

import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from artifacts import make_burn
from images import MIB, check_disk, check_uimage, read_burn, sha256, sparse_size

spec = importlib.util.spec_from_file_location("gen_sdcard", ROOT / "onecloud/target/image/gen_sdcard.py")
disk_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(disk_module)


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


class Images(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="onecloud-image-tests-")
        cls.work = Path(cls.temporary.name)
        cls.boot = cls.work / "boot.fat"
        cls.rootfs = cls.work / "rootfs.ext4"
        cls.disk = cls.work / "external.img"
        run("mkfs.fat", "--invariant", "-F", "16", "-C", cls.boot, "262144")
        with cls.rootfs.open("wb") as file:
            file.truncate(32 * MIB)
        run("mkfs.ext4", "-q", "-F", cls.rootfs)
        payload = cls.work / "kernel.bin"
        payload.write_bytes(b"test-kernel-payload" * 10)
        cls.kernel = cls.work / "uImage"
        run("mkimage", "-A", "arm", "-O", "linux", "-T", "kernel", "-C", "none",
            "-a", "0x00208000", "-e", "0x00208000", "-d", payload, cls.kernel)
        run("mcopy", "-i", cls.boot, cls.kernel, "::uImage")
        disk_module.create_disk(cls.disk, cls.boot, cls.rootfs, "1234abcd")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_filesystems_fit_the_external_disk(self):
        layout = check_disk(self.disk)
        self.assertEqual(layout["root"]["start"], 272 * MIB)
        self.assertEqual(layout["signature"] + "-02", "1234abcd-02")

    def test_partition_outside_the_image_is_rejected(self):
        bad = self.work / "bad-mbr.img"
        with self.disk.open("rb") as original:
            header = bytearray(original.read(512))
        struct.pack_into("<I", header, 474, 0x7FFFFFFF)
        with bad.open("wb") as file:
            file.write(header)
            file.truncate(self.disk.stat().st_size)
        with self.assertRaisesRegex(ValueError, "Root partition"):
            check_disk(bad)

    def test_emmc_and_external_partuuid_cannot_collide(self):
        with self.assertRaisesRegex(ValueError, "different PARTUUID"):
            disk_module.create_disk(self.work / "collision.img", self.boot, self.rootfs, "00002ceb")

    def test_kernel_is_a_verified_legacy_arm_image(self):
        self.assertEqual(check_uimage(self.kernel), b"test-kernel-payload" * 10)
        bad = self.work / "bad-uImage"
        payload = bytearray(self.kernel.read_bytes())
        payload[-1] ^= 1
        bad.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "checksum"):
            check_uimage(bad)

    def test_sparse_header_cannot_claim_extra_blocks(self):
        sparse = self.work / "rootfs.sparse"
        run("img2simg", self.rootfs, sparse, "4096")
        with sparse.open("rb") as source:
            self.assertEqual(sparse_size(source, 0, sparse.stat().st_size), 32 * MIB)
        with sparse.open("r+b") as source:
            source.seek(16)
            blocks = struct.unpack("<I", source.read(4))[0]
            source.seek(16)
            source.write(struct.pack("<I", blocks + 1))
        with sparse.open("rb") as source, self.assertRaisesRegex(ValueError, "length mismatch"):
            sparse_size(source, 0, sparse.stat().st_size)

    @unittest.skipUnless(os.environ.get("ONECLOUD_BOOTLOADER_DIR"), "Set ONECLOUD_BOOTLOADER_DIR for the real Amlogic packer test")
    def test_usb_burning_tool_container_round_trip(self):
        tools = Path(os.environ["ONECLOUD_BOOTLOADER_DIR"])
        base, packer = tools / "u-boot.burn.img", tools / "AmlImg"
        import json
        lock = json.loads((ROOT / "onecloud/sources.json").read_text())
        self.assertEqual(sha256(base), lock["uboot"]["sha256"])
        burn = self.work / "test.burn.img"
        make_burn(base, packer, self.boot, self.rootfs, burn, self.work / "packing")
        unpacked = self.work / "unpacked"
        unpacked.mkdir()
        run(packer, "unpack", burn, unpacked)
        self.assertEqual(len(read_burn(burn)), 12)
        # The original packer's own CRC reader must accept our produced image.
        self.assertEqual(len((unpacked / "commands.txt").read_text().splitlines()), 12)
        bad = self.work / "bad.burn.img"
        shutil.copyfile(burn, bad)
        with bad.open("r+b") as file:
            file.seek(-1, 2)
            value = file.read(1)[0]
            file.seek(-1, 2)
            file.write(bytes([value ^ 1]))
        with self.assertRaisesRegex(ValueError, "CRC mismatch"):
            read_burn(bad)


if __name__ == "__main__":
    unittest.main()
