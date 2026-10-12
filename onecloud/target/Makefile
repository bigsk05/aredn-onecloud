# SPDX-License-Identifier: GPL-2.0-only
# Copyright (C) 2006-2013 OpenWrt.org
# Based on the community OneCloud target by hzyitc and lxhao61.
include $(TOPDIR)/rules.mk

ARCH:=arm
BOARD:=amlogic
BOARDNAME:=Amlogic Meson (OneCloud)
SUBTARGETS:=meson8b
FEATURES:=boot-part rootfs-part ext4 fpu gpio rtc usb
KERNEL_PATCHVER:=6.12
KERNELNAME:=Image dtbs

include $(INCLUDE_DIR)/target.mk

DEFAULT_PACKAGES += blkid e2fsprogs partx-utils kmod-fs-vfat

define Target/Description
  Native AREDN on the Amlogic S805 OneCloud, using its existing U-Boot.
endef

$(eval $(call BuildTarget))
