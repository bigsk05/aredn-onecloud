"""Verify network roles, stable node identity and kernel boot requirements."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate import BOOT_DRIVERS, CONSOLE_INPUT_DRIVERS, DISPLAY_DRIVERS, check_kernel


class Runtime(unittest.TestCase):
    def test_network_modes_preserve_the_dtd_vlan(self):
        script = (ROOT / "onecloud/target/base-files/etc/board.d/02_network").read_text()
        script = "\n".join(line for line in script.splitlines() if not line.startswith(". /lib/"))
        prefix = '''
board_name() { echo thunder,onecloud; }
board_config_update() { :; }
board_config_flush() { :; }
ucidef_set_interfaces_lan_wan() { printf 'lan=%s wan=%s\\n' "$1" "$2"; }
ucidef_set_interface() { printf '%s %s %s %s %s\\n' "$@"; }
'''
        for mode, wanted in (("standard", "lan=eth0 wan=eth0.1"), ("rpi-trunk", "lan=eth0.3 wan=eth0.4")):
            with self.subTest(mode=mode):
                code = script.replace('$(cat /etc/onecloud-network-mode)', mode)
                result = subprocess.check_output(["sh", "-c", prefix + code], text=True)
                self.assertIn(wanted, result)
                self.assertIn("dtdlink device eth0.2 protocol static", result)

    def test_mac_survives_reboots_and_differs_between_devices(self):
        script = (ROOT / "onecloud/target/base-files/lib/preinit/81_onecloud_mac").read_text()
        with tempfile.TemporaryDirectory(prefix="onecloud-mac-") as temporary:
            directory = Path(temporary)
            (directory / "board").write_text("thunder,onecloud\n")
            mmc = directory / "mmc1:0001"
            mmc.mkdir()
            (mmc / "type").write_text("MMC\n")
            code = script.replace("/tmp/sysinfo/board_name", str(directory / "board"))
            code = code.replace("/sys/bus/mmc/devices/*", str(directory / "mmc*"))
            code = 'ip() { echo "$*"; }; boot_hook_add() { "$2"; };\n' + code

            def address(cid):
                (mmc / "cid").write_text(cid + "\n")
                return subprocess.check_output(["sh", "-c", code], text=True).splitlines()[-1].split()[-1]

            a = address("0123456789abcdef0123456789abcdef")
            self.assertEqual(a, address("0123456789abcdef0123456789abcdef"))
            self.assertNotEqual(a, address("1123456789abcdef0123456789abcdef"))
            self.assertRegex(a, r"^02(:[0-9a-f]{2}){5}$")

    def test_modular_usb_root_driver_and_lpae_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "kernel.config"
            drivers = BOOT_DRIVERS | DISPLAY_DRIVERS | CONSOLE_INPUT_DRIVERS
            base = "\n".join(f"CONFIG_{key}=y" for key in sorted(drivers)) + "\nCONFIG_NR_CPUS=4\n"
            config.write_text(base)
            check_kernel(config)
            config.write_text(base.replace("CONFIG_USB_STORAGE=y", "CONFIG_USB_STORAGE=m"))
            with self.assertRaisesRegex(ValueError, "USB_STORAGE"):
                check_kernel(config)
            config.write_text(base + "CONFIG_ARM_LPAE=y\n")
            with self.assertRaisesRegex(ValueError, "LPAE"):
                check_kernel(config)

    def test_modular_console_stack_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "kernel.config"
            base = "\n".join(f"CONFIG_{key}=y" for key in sorted(
                BOOT_DRIVERS | DISPLAY_DRIVERS | CONSOLE_INPUT_DRIVERS))
            base += "\nCONFIG_NR_CPUS=4\n"
            for driver in ("CONFIG_DRM_MESON", "CONFIG_FRAMEBUFFER_CONSOLE", "CONFIG_PHY_MESON8_HDMI_TX",
                        "CONFIG_USB_HID", "CONFIG_HID_SUPPORT"):
                name = driver.removeprefix("CONFIG_")
                with self.subTest(driver=name):
                    config.write_text(base.replace(f"{driver}=y", f"{driver}=n"))
                    with self.assertRaisesRegex(ValueError, name):
                        check_kernel(config)


if __name__ == "__main__":
    unittest.main()
