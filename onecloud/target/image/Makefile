# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/image.mk

define Build/onecloud-boot
	$(if $(filter 256,$(CONFIG_TARGET_KERNEL_PARTSIZE)),,$(error OneCloud boot partition must be 256 MiB))
	sed 's/@ROOTPARTUUID@/$(IMG_PART_SIGNATURE)-02/g' boot.cmd > $@.boot.cmd
	mkimage -A arm -O linux -T script -C none -a 0 -e 0 -n 'AREDN OneCloud' -d $@.boot.cmd $@.boot.scr
	rm -f $@.boot
	mkfs.fat --invariant -F 16 -n AREDN_BOOT -C $@.boot 262144
	mcopy -i $@.boot $@.boot.cmd ::boot.cmd
	mcopy -i $@.boot $@.boot.scr ::boot.scr
	mcopy -i $@.boot $(IMAGE_KERNEL) ::uImage
	mmd -i $@.boot ::dtb
	mcopy -i $@.boot $(KDIR)/image-meson8b-onecloud.dtb ::dtb/meson8b-onecloud.dtb
	python3 gen_sdcard.py $@ $@.boot $(IMAGE_ROOTFS) $(IMG_PART_SIGNATURE)
	rm -f $@.boot $@.boot.cmd $@.boot.scr
endef

define Device/thunder_onecloud
  DEVICE_VENDOR := Xunlei
  DEVICE_MODEL := OneCloud
  DEVICE_VARIANT := S805
  DEVICE_DTS := meson8b-onecloud
  DEVICE_DTS_DIR := $(DTS_DIR)/amlogic
  SUPPORTED_DEVICES := thunder,onecloud xunlei,onecloud
  KERNEL_NAME := Image
  KERNEL_LOADADDR := 0x00208000
  KERNEL_ENTRY := 0x00208000
  KERNEL := kernel-bin | uImage none
  KERNEL_INSTALL := 1
  FILESYSTEMS := ext4
  IMAGES := sdcard.img.gz
  IMAGE/sdcard.img.gz := onecloud-boot | gzip
endef
TARGET_DEVICES += thunder_onecloud

$(eval $(call BuildImage))
