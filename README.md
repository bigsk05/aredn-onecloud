# AREDN for the OneCloud (Amlogic S805)

Native AREDN build for the Xunlei OneCloud: OneCloud U-Boot -> OpenWrt Linux -> AREDN/procd.
Not an AREDN-supported device.

## Build

`.github/workflows/build.yml` is manual only. Inputs: `aredn_tag` (official AREDN release tag such as
`4.26.7.0`, or `latest`), `network_mode`, and optional `publish`. The job checks out that tag, applies
the OneCloud target in `onecloud/target/`, compiles the S805 kernel and AREDN, verifies both image
formats, uploads them as run artifacts, and with `publish` creates a prerelease tagged
`aredn-<version>`.

Local build (Ubuntu 24.04, ASCII path without spaces, 40 GB free):

```sh
python3 scripts/prepare.py "$HOME/build/source" --aredn-tag 4.26.7.0 --network-mode standard
ONECLOUD_JOBS=8 bash scripts/build.sh "$HOME/build/source"
python3 scripts/bootloader.py "$HOME/build/bootloader"
python3 scripts/artifacts.py "$HOME/build/source" "$HOME/build/bootloader" "$HOME/build/artifacts"
```

`scripts/validate.py` runs as part of the build and fails on the wrong target, CPU architecture,
missing AREDN packages, or any boot / HDMI / console-input driver set to module.

## Images

| File | Use |
| --- | --- |
| `*-thunder_onecloud-ext4-sdcard.img.gz` | Uncompress, write to a whole USB stick or SD card. Needs a OneCloud U-Boot that loads `boot.scr`. |
| `*.burn.img.xz` | Uncompress, open in Amlogic USB Burning Tool to write eMMC. Not a raw disk image; never `dd` it. |
| `*-packages.tar.gz` | Signed APK repositories for this firmware. |
| `uImage`, `onecloud.dtb`, `kernel.config`, `*.manifest`, `*.buildinfo`, `source.json` | Kernel, device tree and build provenance. |
| `onecloud-port-source.tar.gz`, `onecloud-aredn.patch` | Board port and the diff applied to official AREDN. |

```sh
cd <artifact dir> && sha256sum -c sha256sums
```

In-place `sysupgrade` is refused; update by reflashing.

## Network

One onboard gigabit port, no onboard radio; use it for wired DtD, tunnels and routing.

| `network_mode` | LAN | WAN | DtD |
| --- | --- | --- | --- |
| `standard` | `eth0` | `eth0.1` (VLAN 1) | `eth0.2` (VLAN 2) |
| `rpi-trunk` | `eth0.3` | `eth0.4` | `eth0.2` |

`standard` suits a direct PC test: the PC takes DHCP from the board and the initial management address
is `http://192.168.1.1/`. `rpi-trunk` matches the VLAN trunk used by the Raspberry Pi images and needs
a VLAN-aware switch. The MAC address is derived from the soldered eMMC CID: stable across reboots,
unique per board.

## Console

HDMI is the local console (`console=tty1 console=ttyAML0,115200n8`, getty on `tty1`, USB keyboard
supported, up to 1080p). Mainline Linux has no Meson8/Meson8b display support, so the drivers come
from the out-of-tree patches in `onecloud/target/patches-6.12/`, adapted to this kernel; see
`THIRD_PARTY.md`.

## Packages

```sh
mkdir -p /opt/aredn-packages
tar -xzf /tmp/aredn-<version>-packages.tar.gz -C /opt/aredn-packages
apk update
```

Use the packages archive from the same run as the firmware; its signing key is already in the image.

## Issues

<https://github.com/bigsk05/aredn-onecloud/issues>
