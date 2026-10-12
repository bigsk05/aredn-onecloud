"""Exercise the same signed-index model used by OpenWrt APK repositories."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from artifacts import verify_repository


@unittest.skipUnless(os.environ.get("ONECLOUD_APK"), "Set ONECLOUD_APK to the compiled OpenWrt host apk tool")
class Repositories(unittest.TestCase):
    def test_signed_index_authenticates_unsigned_packages(self):
        apk = Path(os.environ["ONECLOUD_APK"]).resolve()

        def run(*args):
            subprocess.run([str(arg) for arg in args], check=True, capture_output=True)

        with tempfile.TemporaryDirectory(prefix="onecloud-repository-") as temporary:
            work = Path(temporary)
            keys, repo, files = (work / name for name in ("keys", "repo", "files"))
            for path in (keys, repo, files):
                path.mkdir()
            private = work / "private-key.pem"
            run("openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", private)
            run("openssl", "pkey", "-in", private, "-pubout", "-out", keys / "public-key.pem")
            package = repo / "onecloud-test-1.0-r0.apk"

            def create_package(payload):
                (files / "payload.txt").write_text(payload)
                package.unlink(missing_ok=True)
                run(apk, "mkpkg", "--root", work, "--info", "name:onecloud-test",
                    "--info", "version:1.0-r0", "--info", "arch:noarch",
                    "--info", "description:OneCloud repository test", "--info", "license:MIT",
                    "--files", files, "--output", package)

            create_package("Original payload\n")
            run(apk, "mkndx", "--root", work, "--keys-dir", keys, "--allow-untrusted",
                "--sign-key", private, "--output", repo / "packages.adb", package)
            # A valid OpenWrt-style repository has a signed index and an
            # unsigned package. The archive must pass without re-signing it.
            verify_repository(apk, repo, [package], keys)

            # Repack a different payload with valid internal checksums and
            # the same name/version. Only the signed index authenticates it.
            create_package("Changed payload\n")
            with self.assertRaisesRegex(ValueError, "do not match their signed index"):
                verify_repository(apk, repo, [package], keys)


if __name__ == "__main__":
    unittest.main()
