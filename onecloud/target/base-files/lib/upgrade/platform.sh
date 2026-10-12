#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# The factory images include board-specific disk layouts. Do not fall through
# to default_do_upgrade(), which is intended for MTD devices.
platform_check_image() {
    echo 'OneCloud experimental port: use an external-media image or a USB Burning Tool factory image; in-place sysupgrade is not implemented.' >&2
    return 1
}

platform_do_upgrade() {
    platform_check_image "$@"
}
