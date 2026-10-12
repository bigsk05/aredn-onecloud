# SPDX-License-Identifier: GPL-2.0-only
# hzyitc U-Boot sets bootdev to "usb 0", "mmc 0" or "mmc 1".
# Avoid "test -z": this old U-Boot has a known implementation bug.
if test -n "${bootdev}"; test $? != 0; then
    echo 'Set bootdev before loading boot.scr (usb 0, mmc 0, or mmc 1).'
    exit 1
fi

echo "Booting AREDN OneCloud from ${bootdev}"
# console=tty1 first, serial last: /dev.console input stays on the UART while
# the HDMI framebuffer VT still shows the boot log, as in the official Pi images.
setenv bootargs "root=PARTUUID=@ROOTPARTUUID@ rootfstype=ext4 rootwait rw console=tty1 console=ttyAML0,115200n8 no_console_suspend consoleblank=0 net.ifnames=0"
# Load above the kernel's final address, as in the tested Armbian image.
fatload ${bootdev} 0x20800000 uImage || exit 1
fatload ${bootdev} 0x21800000 dtb/meson8b-onecloud.dtb || exit 1
# No Armbian initrd: MMC, USB storage and ext4 must be built into this kernel.
bootm 0x20800000 - 0x21800000
