# Third-party sources and licences

AREDN, OpenWrt, Linux and every package keep their own copyright and licence. Pinned revisions are
recorded in `onecloud/sources.json` and in each build's `source.json`.

| Component | Use here | Licence |
| --- | --- | --- |
| [AREDN](https://github.com/aredn/aredn) | Official release checked out per `aredn_tag`; this port adds a target and build config only | GPL-2.0 plus the trademark terms of `AREDNLicense.txt`, shipped with the artifacts |
| [OpenWrt](https://github.com/openwrt/openwrt) / Linux | System, kernel and packages, as pinned by the selected AREDN release | `COPYING` and per-file notices |
| [lxhao61/OneCloud-OpenWrt](https://github.com/lxhao61/OneCloud-OpenWrt/tree/6202bb5ac3ab3dcea00faea079e64532776cacd3/target/linux/amlogic) | `meson8b/config-6.12` seed, OneCloud DTS, MMC/PWM patches | GPL-2.0-only per file; that repository also carries the MIT text below |
| [armbian/build](https://github.com/armbian/build/tree/v25.8.1) `patch/kernel/archive/meson-6.12` | 24 Meson8/Meson8b display patches, vendored as `910`–`933`, refreshed for Linux 6.12.94, kHz changed to Hz in `923` and `928` | GPL-2.0-only; upstream author Martin Blumenstingl (`xdarklight/linux` `meson-mx-integration-*`), board DTS by hzyitc |
| [hzyitc/u-boot](https://github.com/hzyitc/u-boot/tree/0038d741ed1c77a77570c3a6bf88fe6189c11733) | `build-20221028-0940/eMMC.burn.img` downloaded, SHA-256 verified, boot components kept byte for byte | U-Boot `COPYING` and per-file notices |
| [hzyitc/AmlImg](https://github.com/hzyitc/AmlImg/tree/5ede4ed30b27c10187af5258f7e2f61f9ad71e1e) | Built at build time to pack the eMMC image; not shipped inside the firmware | BSD-3-Clause, text below |

`onecloud-port-source.tar.gz` in each release carries the board target, the scripts and the diff
applied to official AREDN, so the GPL sources of the firmware stay available.

## OneCloud-OpenWrt MIT

```text
MIT License

Copyright (c) 2019-2023 P3TERX <https://p3terx.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## AmlImg BSD-3-Clause

```text
BSD 3-Clause License

Copyright (c) 2021, hzyitc
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```
