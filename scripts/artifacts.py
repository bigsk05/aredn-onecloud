#!/usr/bin/env python3
"""Package and verify external-media and USB Burning Tool firmware together."""

import argparse
import gzip
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from images import BOOT_SIZE, MIB, check_burn, check_disk, check_uimage, copy_region, read_burn, sha256
from prepare import ROOT, port_hash
from validate import check_build, require


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def add_file(archive, path, name, epoch):
    path = Path(path)
    info = tarfile.TarInfo(name)
    info.size = path.stat().st_size
    info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
    info.mtime = epoch
    with path.open("rb") as source:
        archive.addfile(info, source)


def verify_repository(apk, repo, packages, keys):
    index = repo / "packages.adb"
    options = ("--root", keys, "--keys-dir", keys)
    run(apk, "verify", "--quiet", *options, index)

    def entries(path):
        data = json.loads(subprocess.check_output(
            [str(apk), "adbdump", "--format", "json", str(path)]))
        return sorted(data.get("packages", []), key=lambda item: (item["name"], item["version"], item.get("arch", "")))

    expected = entries(index)
    if not packages:
        require(not expected, f"Index references missing packages: {repo}")
        return
    # OpenWrt signs indexes, not individual APK files. Check each package's
    # internal data checksums, then recompute its metadata hash and compare
    # with the authenticated index. --allow-untrusted applies only to these
    # raw package reads; the original index above must pass signature checks.
    run(apk, "verify", "--quiet", "--allow-untrusted", *options, *packages)
    recreated = keys / "recreated.adb"
    run(apk, "mkndx", "--allow-untrusted", *options, "--output", recreated, *packages)
    require(entries(recreated) == expected, f"Packages do not match their signed index: {repo}")
    recreated.unlink()


def package_repositories(source, cfg, target, output, epoch):
    openwrt = source / "openwrt"
    binaries = openwrt / "bin"
    root = binaries / "packages/arm_cortex-a5_neon-vfpv4"
    key = openwrt / "public-key.pem"
    require(key.is_file() and "BEGIN PUBLIC KEY" in key.read_text(), "Missing APK public key")
    required = {"base"} | {key.removeprefix("CONFIG_FEED_") for key, value in cfg.items() if key.startswith("CONFIG_FEED_") and value == "y"}
    # OpenWrt omits empty feed indexes, although it writes those feeds to the
    # image's repository list. Add signed empty indexes so apk update succeeds.
    for feed in sorted(required):
        repo = root / feed
        repo.mkdir(parents=True, exist_ok=True)
        index = repo / "packages.adb"
        if not index.exists():
            require(feed != "base" and not any(repo.glob("*.apk")), f"Missing populated feed index: {feed}")
            run(openwrt / "staging_dir/host/bin/apk", "mkndx", "--root", openwrt,
                "--keys-dir", openwrt, "--description", f"No packages selected from {feed}",
                "--sign-key", openwrt / "private-key.pem", "--output", index)
    repos = [target / "packages", *sorted(path for path in root.iterdir() if path.is_dir())]
    with tempfile.TemporaryDirectory(prefix="onecloud-keys-", dir=source.parent) as temporary:
        keys = Path(temporary)
        shutil.copy2(key, keys / key.name)
        with output.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=epoch, filename="") as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                add_file(archive, key, "keys/public-key.pem", epoch)
                for repo in repos:
                    index = repo / "packages.adb"
                    packages = sorted(repo.glob("*.apk"))
                    if not packages and not index.exists():
                        continue
                    require(index.is_file(), f"Missing signed index: {repo}")
                    # Trust only the public key installed in this firmware.
                    verify_repository(openwrt / "staging_dir/host/bin/apk", repo, packages, keys)
                    for path in [index, *packages]:
                        add_file(archive, path, str(path.relative_to(binaries)), epoch)


def check_root_files(rootfs, source, plan):
    expected = {
        "/etc/mesh-release": (plan["version"] + "\n").encode(),
        "/etc/aredn-onecloud": (plan["version"] + "\n").encode(),
        "/etc/onecloud-network-mode": (plan["network_mode"] + "\n").encode(),
        "/etc/apk/keys/public-key.pem": (source / "openwrt/public-key.pem").read_bytes(),
    }
    for name, content in expected.items():
        actual = subprocess.run(["debugfs", "-R", "cat " + name, str(rootfs)],
                                check=True, capture_output=True).stdout
        require(actual == content, f"Wrong or missing file in built rootfs: {name}")


def check_boot_files(boot, work, root_uuid):
    work.mkdir()
    for source, name in (("uImage", "uImage"), ("boot.scr", "boot.scr"),
                         ("boot.cmd", "boot.cmd"), ("dtb/meson8b-onecloud.dtb", "onecloud.dtb")):
        run("mcopy", "-i", boot, "::" + source, work / name)
    check_uimage(work / "uImage")
    script = check_uimage(work / "boot.scr", image_type=6)
    text = (work / "boot.cmd").read_bytes()
    require(text in script and f"root=PARTUUID={root_uuid}".encode() in text, "Boot script points to the wrong root filesystem")
    require(b"bootm 0x20800000 - 0x21800000" in text, "Unexpected boot command/initrd requirement")
    compatible = subprocess.check_output(
        ["fdtget", "-t", "s", str(work / "onecloud.dtb"), "/", "compatible"], text=True,
    ).split()
    require("thunder,onecloud" in compatible and "amlogic,meson8b" in compatible, "Wrong board DTB")
    return work


def make_burn(base, packer, boot, rootfs, destination, work):
    """Keep every verified bootloader component unchanged; append two filesystems."""
    work.mkdir()
    read_burn(base)
    run(packer, "unpack", base, work)
    for name, raw in (("boot", boot), ("rootfs", rootfs)):
        sparse = work / f"{name}.sparse"
        run("img2simg", raw, sparse, "4096")
        with sparse.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha1").hexdigest()
        (work / f"{name}.VERIFY").write_text("sha1sum " + digest)
        with (work / "commands.txt").open("a") as commands:
            commands.write(f"PARTITION:{name}:sparse:{name}.sparse\nVERIFY:{name}:normal:{name}.VERIFY\n")
    run(packer, "pack", destination, work)
    items = check_burn(destination, base, rootfs.stat().st_size)
    # Independently decode both sparse payloads and compare with the inputs.
    # This verifies the actual bytes that USB Burning Tool will write.
    for name, original in (("boot", boot), ("rootfs", rootfs)):
        item = items[("PARTITION", name)]
        extracted = work / f"{name}.extracted.sparse"
        restored = work / f"{name}.restored"
        copy_region(destination, item["offset"], item["size"], extracted)
        run("simg2img", extracted, restored)
        require(sha256(restored) == sha256(original), f"Sparse round-trip mismatch: {name}")
        extracted.unlink()
        restored.unlink()
    return items


def stage(source, bootloader_dir, output):
    cfg, plan, target, kernel_config = check_build(source)
    require(port_hash() == plan["port_sha256"], "Port sources changed after preparation; rebuild from matching sources before packaging")
    require(not output.exists() or not any(output.iterdir()), "Use an empty artifact directory")
    output.mkdir(parents=True, exist_ok=True)
    epoch = plan["source_date_epoch"]
    os.environ["SOURCE_DATE_EPOCH"] = str(epoch)
    version = plan["version"]
    base = bootloader_dir / "u-boot.burn.img"
    require(sha256(base) == plan["sources"]["uboot"]["sha256"], "Wrong bootloader template")
    profile = json.loads((target / "profiles.json").read_text())["profiles"]["thunder_onecloud"]
    images = [item for item in profile["images"] if item["name"].endswith("-sdcard.img.gz")]
    require(len(images) == 1, "Expected one external-media image")
    item = images[0]
    name = item["name"]
    require(Path(name).name == name and name.startswith(f"aredn-{version}-"), "Unexpected image filename")
    image = target / name
    require(image.stat().st_size == item["size"] and sha256(image) == item["sha256"], "profiles.json image checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="onecloud-stage-", dir=source.parent) as temporary:
        work = Path(temporary)
        disk, boot, rootfs = (work / name for name in ("disk.img", "boot.fat", "rootfs.ext4"))
        with gzip.open(image, "rb") as src, disk.open("wb") as dst:
            shutil.copyfileobj(src, dst, MIB)
        layout = check_disk(disk)
        for name, destination in (("boot", boot), ("root", rootfs)):
            partition = layout[name]
            copy_region(disk, partition["start"], partition["size"], destination)
        require(rootfs.stat().st_size == 256 * MIB, "Unexpected rootfs size")
        run("e2fsck", "-fn", rootfs)
        check_root_files(rootfs, source, plan)
        extracted = check_boot_files(boot, work / "external-boot", layout["signature"] + "-02")
        # eMMC retains the verified bootloader's MBR, including its signature.
        # The external image has a different PARTUUID, so an attached USB stick
        # cannot silently become the eMMC firmware's root filesystem.
        emmc_uuid = plan["sources"]["uboot"]["emmc_signature"] + "-02"
        text = (extracted / "boot.cmd").read_text().replace(layout["signature"] + "-02", emmc_uuid)
        (work / "boot.cmd").write_text(text)
        run("mkimage", "-A", "arm", "-O", "linux", "-T", "script", "-C", "none", "-a", "0", "-e", "0",
            "-n", "AREDN OneCloud", "-d", work / "boot.cmd", work / "boot.scr")
        run("mcopy", "-o", "-i", boot, work / "boot.cmd", "::boot.cmd")
        run("mcopy", "-o", "-i", boot, work / "boot.scr", "::boot.scr")
        check_boot_files(boot, work / "emmc-boot", emmc_uuid)
        burn = work / f"aredn-{version}.burn.img"
        make_burn(base, bootloader_dir / "AmlImg", boot, rootfs, burn, work / "burn")
        with burn.open("rb") as src, lzma.open(output / (burn.name + ".xz"), "wb", preset=6) as dst:
            shutil.copyfileobj(src, dst, MIB)
        shutil.copy2(image, output / image.name)
        for name in ("uImage", "onecloud.dtb"):
            shutil.copy2(extracted / name, output / name)
        plan["external_disk"] = layout
        plan["emmc_root_partuuid"] = emmc_uuid
        plan["checks"] = ["target-and-feeds", "kernel-built-in-drivers", "aredn-manifest", "installed-rootfs-metadata",
                          "mbr-and-ext4", "uboot-crc-and-dtb", "burn-crc-and-sha1", "sparse-round-trip"]
    for pattern in ("*.manifest", "*.buildinfo", "profiles.json"):
        for path in target.glob(pattern):
            shutil.copy2(path, output / path.name)
    shutil.copy2(kernel_config, output / "kernel.config")
    shutil.copy2(source / "onecloud-aredn.patch", output / "onecloud-aredn.patch")
    shutil.copy2(source / "AREDNLicense.txt", output / "AREDNLicense.txt")
    shutil.copy2(source / "LICENSE", output / "LICENSE.AREDN")
    shutil.copy2(source / "openwrt/COPYING", output / "LICENSE.OpenWrt")
    shutil.copy2(ROOT / "THIRD_PARTY.md", output / "THIRD_PARTY.md")
    package_repositories(source, cfg, target, output / f"aredn-{version}-packages.tar.gz", epoch)
    plan["checks"].append("apk-signed-index-and-package-hashes")
    with (output / "onecloud-port-source.tar.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=epoch, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path in sorted((source / "openwrt/target/linux/amlogic").rglob("*")):
                if path.is_file():
                    add_file(archive, path, "target/linux/amlogic/" + str(path.relative_to(source / "openwrt/target/linux/amlogic")), epoch)
            for relative in ("configs/amlogic-meson8b.config", "files/etc/aredn-onecloud", "files/etc/onecloud-network-mode", "feeds.conf", "onecloud-aredn.patch", "LICENSE", "AREDNLicense.txt"):
                add_file(archive, source / relative, "aredn/" + relative, epoch)
            for directory in (".github", "onecloud", "scripts", "tests"):
                for path in sorted((ROOT / directory).rglob("*")):
                    if path.is_file() and "__pycache__" not in path.parts:
                        add_file(archive, path, "port/" + str(path.relative_to(ROOT)), epoch)
            for relative in ("README.md", "THIRD_PARTY.md", "LICENSE", ".gitignore"):
                add_file(archive, ROOT / relative, "port/" + relative, epoch)
    plan["feed_revisions"] = {
        path.name: subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
        for path in sorted((source / "openwrt/feeds").iterdir()) if (path / ".git").exists()
    }
    (output / "source.json").write_text(json.dumps(plan, indent=2) + "\n")
    (output / "FLASHING.txt").write_text(
        f"AREDN {version} / OneCloud S805 / experimental native port\n"
        f"Network mode: {plan['network_mode']}\n"
        "*-sdcard.img.gz: decompress and write as a raw USB/SD disk; requires OneCloud U-Boot.\n"
        "*.burn.img.xz: decompress and open in Amlogic USB Burning Tool; overwrites eMMC.\n"
        "Do not use a raw disk writer for a .burn.img. In-place sysupgrade is disabled.\n"
        "Console: HDMI (tty1, up to 1080p, video only) and 115200 8N1 on the UART pads.\n"
        "No physical OneCloud boot test has been performed by this build. See repository README.\n"
    )
    (output / "sha256sums").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in sorted(output.iterdir()) if path.is_file()))
    print(f"Verified and staged both OneCloud image formats: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("bootloader_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        stage(args.source.resolve(), args.bootloader_dir.resolve(), args.output.resolve())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"OneCloud packaging failed: {error}\n")
