#!/usr/bin/env python3
"""Fail builds with a wrong CPU, missing AREDN packages or modular root drivers."""

import argparse
import json
from pathlib import Path
import re
import subprocess

CORE_PACKAGES = {
    "base-files", "kernel", "apk-mbedtls", "arednlink", "babel", "firewall4",
    "ucode", "uhttpd", "uhttpd-mod-ucode", "wireguard-tools", "fwtool",
}
BOOT_DRIVERS = {
    "ARM", "ARCH_MESON", "MACH_MESON8", "SMP", "SERIAL_MESON",
    "SERIAL_MESON_CONSOLE", "MMC", "MMC_BLOCK", "MMC_MESON_MX_SDHC",
    "MMC_MESON_MX_SDIO", "EXT4_FS", "USB", "USB_DWC2", "PHY_MESON8B_USB2",
    "USB_STORAGE", "SCSI", "BLK_DEV_SD", "STMMAC_ETH", "DWMAC_MESON", "REALTEK_PHY",
    "MSDOS_PARTITION", "PWRSEQ_EMMC", "COMMON_CLK_MESON8B", "PINCTRL_MESON8B",
    "RESET_MESON", "REGULATOR_FIXED_VOLTAGE", "REGULATOR_PWM", "PWM_MESON",
}
# There is no initrd, so the HDMI console has to be ready when the root
# filesystem is mounted; every driver below must be built into the kernel.
DISPLAY_DRIVERS = {
    "DRM", "DRM_MESON", "DRM_MESON_TRANSWITCH_HDMI", "DRM_FBDEV_EMULATION",
    "MESON_CANVAS", "PHY_MESON8_HDMI_TX", "PHY_MESON_CVBS_DAC", "FB",
    "FRAMEBUFFER_CONSOLE", "VT", "VT_CONSOLE",
}
# Official AREDN ships these as kmod-hid/kmod-usb-hid; here they are built in
# so the HDMI console accepts a keyboard even before any package is loaded.
CONSOLE_INPUT_DRIVERS = {"HID_SUPPORT", "HID", "HID_GENERIC", "USB_HID"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_config(path):
    return dict(re.findall(r"^(CONFIG_\S+)=(.*)$", Path(path).read_text(), re.M))


def check_config(source):
    plan = json.loads((source / "onecloud-build.json").read_text())
    cfg = read_config(source / "openwrt/.config")
    expected = {
        "CONFIG_TARGET_amlogic": "y",
        "CONFIG_TARGET_amlogic_meson8b": "y",
        "CONFIG_TARGET_ARCH_PACKAGES": '"arm_cortex-a5_neon-vfpv4"',
        "CONFIG_TARGET_ROOTFS_EXT4FS": "y",
        "CONFIG_TARGET_KERNEL_PARTSIZE": "256",
        "CONFIG_TARGET_ROOTFS_PARTSIZE": "256",
        "CONFIG_USE_APK": "y",
        "CONFIG_SIGNED_PACKAGES": "y",
        "CONFIG_DEVEL": "y",
        "CONFIG_CCACHE": "y",
        "CONFIG_AUTOREMOVE": "y",
        "CONFIG_VERSION_DIST": '"AREDN"',
        "CONFIG_VERSION_NUMBER": json.dumps(plan["version"]),
        "CONFIG_VERSION_REPO": '"/opt/aredn-packages"',
    }
    expected.update({f"CONFIG_PACKAGE_{name}": "y" for name in CORE_PACKAGES - {"kernel"}})
    for key, value in expected.items():
        require(cfg.get(key) == value, f"{key}: expected {value}, got {cfg.get(key)}")
    for key in ("CONFIG_TARGET_armsr", "CONFIG_aarch64", "CONFIG_TARGET_ROOTFS_SQUASHFS", "CONFIG_TARGET_ROOTFS_INITRAMFS"):
        require(cfg.get(key, "n") == "n", f"Wrong target or image type: {key}")
    for name, feed in plan["sources"]["feeds"].items():
        checkout = source / "openwrt/feeds" / name
        require(checkout.is_dir(), f"Feed not installed: {name}")
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
        require(re.fullmatch(r"[0-9a-f]{40}", actual), f"Feed checkout is not a commit: {name}")
        if "commit" in feed:
            require(actual == feed["commit"], f"Feed revision mismatch: {name}")
    return cfg, plan


def check_kernel(path):
    cfg = read_config(path)
    labels = {}
    for driver in BOOT_DRIVERS:
        labels["CONFIG_" + driver] = "Boot-critical driver"
    for driver in DISPLAY_DRIVERS:
        labels["CONFIG_" + driver] = "HDMI console driver"
    for driver in CONSOLE_INPUT_DRIVERS:
        labels.setdefault("CONFIG_" + driver, "Console input driver")
    for name, label in labels.items():
        require(cfg.get(name) == "y", f"{label} must be built in: {name.removeprefix('CONFIG_')}")
    require(cfg.get("CONFIG_ARM_LPAE", "n") == "n", "Cortex-A5 does not support an ARM LPAE kernel")
    require(cfg.get("CONFIG_NR_CPUS") == "4", "S805 must support all four cores")
    return cfg


def check_build(source):
    cfg, plan = check_config(source)
    configs = list((source / "openwrt/build_dir").glob("target-*/linux-amlogic_meson8b/linux-*/.config"))
    require(len(configs) == 1, "Expected exactly one OneCloud kernel configuration")
    check_kernel(configs[0])
    target = source / "openwrt/bin/targets/amlogic/meson8b"
    info = json.loads((target / "profiles.json").read_text())
    require(info["target"] == "amlogic/meson8b", "Wrong output target")
    require(info["version_number"] == plan["version"], "Stale firmware version")
    require(info["arch_packages"] == "arm_cortex-a5_neon-vfpv4", "Wrong package CPU architecture")
    require(set(info["profiles"]) == {"thunder_onecloud"}, "Wrong device profile")
    manifests = list(target.glob("*.manifest"))
    require(len(manifests) == 1, "Expected one device package manifest")
    installed = {line.split(" - ", 1)[0] for line in manifests[0].read_text().splitlines()}
    require(CORE_PACKAGES <= installed, f"Missing AREDN packages: {CORE_PACKAGES - installed}")
    require((source / "files/etc/mesh-release").read_text().strip() == plan["version"], "Wrong AREDN UI version")
    return cfg, plan, target, configs[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("config", "build"))
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        (check_config if args.command == "config" else check_build)(args.source.resolve())
        print(f"OneCloud {args.command} checks passed")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"OneCloud validation failed: {error}\n")


if __name__ == "__main__":
    main()
