#!/usr/bin/env python3
"""Prepare an official AREDN release for the native OneCloud target."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / "onecloud/sources.json").read_text())


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replace_once(path, before, after):
    text = path.read_text()
    require(text.count(before) == 1, f"Upstream changed; review required: {path} / {before!r}")
    path.write_text(text.replace(before, after))


def port_hash():
    digest = hashlib.sha256()
    for directory in ("onecloud", "scripts"):
        for path in sorted((ROOT / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def remote_refs(url):
    refs = {}
    for line in subprocess.check_output(["git", "ls-remote", "--tags", url], text=True).splitlines():
        if "\t" not in line:
            continue
        sha, ref = line.split("\t", 1)
        if ref.endswith("^{}"):
            refs[ref[:-3]] = sha
        else:
            refs.setdefault(ref, sha)
    return refs


def resolve_ref(url, wanted):
    """Map a release tag or commit to a commit hash."""
    refs = remote_refs(url)
    if re.fullmatch(r"[0-9a-f]{40}", wanted):
        return wanted
    for ref in (f"refs/tags/{wanted}^{{}}", f"refs/tags/{wanted}", f"refs/heads/{wanted}"):
        if ref in refs:
            return refs[ref]
    raise ValueError(f"Ref not found on {url}: {wanted}")


def latest_tag(url):
    prefix = len("refs/tags/")
    tags = [ref[prefix:] for ref in remote_refs(url) if re.fullmatch(r"\d+(\.\d+){2,3}", ref[prefix:])]
    require(tags, "No numeric release tags on the AREDN repository")
    return max(tags, key=lambda tag: [int(part) for part in (tag.split(".") + ["0"])[:4]])


def checkout(url, commit, path):
    path.mkdir(parents=True)
    run("git", "init", "-q", str(path))
    run("git", "remote", "add", "origin", url, cwd=path)
    run("git", "fetch", "--depth=1", "origin", commit, cwd=path)
    run("git", "-c", "advice.detachedHead=false", "checkout", "--detach", "FETCH_HEAD", cwd=path)
    require(git("rev-parse", "HEAD", cwd=path) == commit, "AREDN checkout does not match the tag")


def openwrt_source(aredn_dir):
    match = re.search(r"^OPENWRT_SRC=(\S+)", (aredn_dir / "openwrt.mk").read_text(), re.M)
    require(match, "Cannot read OPENWRT_SRC from openwrt.mk")
    return match.group(1)


def openwrt_ref(aredn_dir):
    match = re.search(r"^OPENWRT_COMMIT=(\S+)", (aredn_dir / "openwrt.mk").read_text(), re.M)
    require(match, "Cannot read OPENWRT_COMMIT from openwrt.mk")
    return match.group(1)


def feed_declarations(aredn_dir):
    """Official AREDN declares its own feeds; OpenWrt's pinned default feeds add the rest."""
    feeds = {}
    for line in (aredn_dir / "feeds.conf").read_text().splitlines():
        match = re.fullmatch(r"src-git\s+(\S+)\s+(\S+)", line)
        if not match:
            continue
        name, spec = match.groups()
        for separator, kind in (("^", "commit"), (";", "branch")):
            if separator in spec:
                url, _, ref = spec.partition(separator)
                feeds[name] = {"url": url, kind: ref}
                break
        else:
            feeds[name] = {"url": spec, "branch": "default"}
    require(feeds, "The official feeds.conf declares no feeds")
    return feeds


def prepare(destination, tag, network_mode):
    if not str(destination).isascii() or any(c.isspace() for c in str(destination)):
        raise ValueError("Use an ASCII build path without spaces, for example /tmp/aredn-onecloud-build")
    require(not destination.exists(), f"Destination must not exist: {destination}")

    if not tag or tag == "latest":
        tag = latest_tag(LOCK["aredn"]["url"])
    commit = resolve_ref(LOCK["aredn"]["url"], tag)
    version = f"{tag}-onecloud"
    digest = port_hash()
    checkout(LOCK["aredn"]["url"], commit, destination)

    makefile = destination / "Makefile"
    replace_once(
        makefile,
        "\tgit clone $(OPENWRT_SRC) $(OPENWRT_DIR)\n\tcd $(OPENWRT_DIR); git checkout $(OPENWRT_COMMIT)\n",
        "\tgit init $(OPENWRT_DIR)\n"
        "\tgit -C $(OPENWRT_DIR) remote add origin $(OPENWRT_SRC)\n"
        "\tgit -C $(OPENWRT_DIR) fetch --depth=1 origin $(OPENWRT_COMMIT)\n"
        "\tgit -C $(OPENWRT_DIR) checkout --detach FETCH_HEAD\n",
    )
    replace_once(
        makefile,
        "GIT_BRANCH=$(shell git symbolic-ref HEAD | sed -e 's,.*/\\(.*\\),\\1,')",
        "GIT_BRANCH=$(shell git symbolic-ref --quiet --short HEAD || echo detached)",
    )

    feeds = feed_declarations(destination)
    openwrt_url = openwrt_source(destination)
    openwrt_pin = openwrt_ref(destination)
    openwrt_commit = resolve_ref(openwrt_url, openwrt_pin)
    shutil.copy2(ROOT / "onecloud/config", destination / "configs/amlogic-meson8b.config")
    files = destination / "files"
    (files / "etc/onecloud-network-mode").write_text(network_mode + "\n")
    (files / "etc/aredn-onecloud").write_text(version + "\n")
    replace_once(files / "app/partial/firmware.ut", 'href="https://github.com/aredn/aredn/issues"',
                 f'href="{LOCK["project"]["issues"]}"')
    radios_path = files / "etc/radios.json"
    radios = json.loads(radios_path.read_text())
    for model in ("thunder onecloud", "xunlei onecloud"):
        require(model not in radios, "Upstream already contains OneCloud: review the port")
        radios[model] = {"name": "Xunlei OneCloud (S805)", "features": ["supernode", "xlink"]}
    radios_path.write_text(json.dumps(radios, indent=2) + "\n")
    canonical = files / "etc/uci-defaults/99_canonical_config"
    for key in ("firmware_aredn", "packages_default"):
        replace_once(canonical, f'{key}: "http://downloads.arednmesh.org"', f'{key}: ""')

    plan = {
        "version": version,
        "network_mode": network_mode,
        "source_date_epoch": int(git("show", "-s", "--format=%ct", "HEAD", cwd=destination)),
        "port_sha256": digest,
        "hardware_tested": tag in LOCK["aredn"]["tested"],
        "sources": {
            "aredn": {"url": LOCK["aredn"]["url"], "tag": tag, "commit": commit},
            "openwrt": {"url": openwrt_url, "ref": openwrt_pin, "commit": openwrt_commit},
            "feeds": feeds,
            "board_support": LOCK["board_support"],
            "display_patches": LOCK["display_patches"],
            "amlimg": LOCK["amlimg"],
            "uboot": LOCK["uboot"],
        },
    }
    (destination / "onecloud-build.json").write_text(json.dumps(plan, indent=2) + "\n")
    run("make", "TARGET=amlogic-meson8b", f"OPENWRT_COMMIT={plan['sources']['openwrt']['commit']}",
        f"FW_VERSION={version}", str(destination / "openwrt"), cwd=destination)
    require(git("rev-parse", "HEAD", cwd=destination / "openwrt") == plan["sources"]["openwrt"]["commit"],
            "OpenWrt checkout does not match openwrt.mk")
    shutil.copytree(ROOT / "onecloud/target", destination / "openwrt/target/linux/amlogic")
    for path in (destination / "openwrt/target/linux/amlogic/base-files").rglob("*"):
        if path.is_file() and path.read_bytes().startswith(b"#!/bin/sh"):
            path.chmod(0o755)
    delta = subprocess.check_output(["git", "diff", "--binary"], cwd=destination)
    (destination / "onecloud-aredn.patch").write_bytes(delta)
    print(f"Prepared AREDN {version} at {destination}")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--aredn-tag", default="latest", help="Official AREDN release tag, or latest")
    parser.add_argument("--network-mode", choices=("standard", "rpi-trunk"), default="standard")
    args = parser.parse_args()
    try:
        plan = prepare(args.destination.resolve(), args.aredn_tag, args.network_mode)
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                print(f"version={plan['version']}", file=output)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"OneCloud source preparation failed: {error}\n")


if __name__ == "__main__":
    main()
