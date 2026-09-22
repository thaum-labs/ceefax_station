# modem73 (HF only)

Ceefax uses this binary only when `[radio] band = "hf"`. A VHF station keeps using Dire Wolf and does not start modem73.

The Windows installer downloads the official Windows port and copies `modem73.exe` into this folder:

https://github.com/RFnexus/modem73-win/releases/download/v2.4.0/modem73_2.4.0_win64.zip

That port is the build the upstream project tells Windows users to run. It is Unlicense, headless via `modem73.exe --headless`, and one version behind the Linux packages (upstream v2.4.2). Linux and Raspberry Pi do not get a binary inside the Ceefax `.deb`; they install the official amd64, arm64, or armhf package from https://github.com/RFnexus/modem73/releases and leave `modem73` on `PATH`.

PTT stays in modem73 (rigctl, serial, or CM108). Ceefax only sets the robust mode for the pass.
