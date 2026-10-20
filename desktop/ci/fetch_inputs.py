#!/usr/bin/env python3
"""Fetch the inputs of the cross-platform generate check, for CI only.

    python3 desktop/ci/fetch_inputs.py <out dir>

Downloads RICOH's official GR III 2.10 zip from RICOH's site (downloading it accepts
RICOH's software licence) and FUJIFILM's GFX ETERNA 55 3D LUT pack from FUJIFILM's
site, checks both against pinned SHA-256, and converts four film simulations with
fuji2gr.py into the sRGB .cube files DARKSLIDE GR imports, checked against the
SHA-256 of the files made on the author's Mac. None of these files is published:
CI keeps them on the runner and uploads only the comparison report.

Writes <out dir>/fwdc239b.bin and <out dir>/<name>.cube, and prints the --lut
arguments for selftest.py.
"""
import hashlib
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RICOH = ("https://www.ricoh-imaging.co.jp/resources/japan/support/download/digital/FIRMWARE/gr3_v210.zip",
         "e895b439e4b3b96ac04f50072f02a63061ec7de5dcc1b070890baa09bc659470")
FIRMWARE = ("fwdc239b.bin", "d6a3c9c288d784080e7b283222ecdd8752adfeed6faa36dab44f73115354bfd4")
FUJI = ("https://dl.fujifilm-x.com/support/lut/gfx-eterna-55-3d-lut-v110.zip",
        "febfc7050999620651ca0cf162bf8b499970ef270b4da632765b61b958cf7940")
FUJI_DIR = "gfx-eterna-55-3d-lut-v110/33Grid/F-Log2/"
# (source in the pack, title, file, preset name in the camera, SHA-256 of the converted .cube)
LUTS = [
    ("FLog2_to_ACROS_33grid_V.1.00.cube", "Acros", "Fuji_Acros_GR3.cube", "ACROS",
     "2bd630512cf4a56ee9b8d987518d1d8b8c28f586f30f1203b45c647bc90fd4dd"),
    ("FLog2_to_CLASSIC-CHROME_33grid_V.1.00.cube", "Classic Chrome", "Fuji_Classic_Chrome_GR3.cube", "CHROME",
     "d5aedd9538e56f2f858d803404fbc2978d5f7fc14875de83c2b5740e7ba7af1e"),
    ("FLog2_to_CLASSIC-Neg._33grid_V.1.00.cube", "Classic Neg", "Fuji_Classic_Neg_GR3.cube", "CL NEG",
     "fdb15bf7f0b13e537b05e33e802abd48a6c6da58251ba3d1b6adf9f374982e90"),
    ("FLog2_to_ETERNA_33grid_V.1.00.cube", "Eterna", "Fuji_Eterna_GR3.cube", "ETERNA",
     "b84a3e0ef8e4e812f085352820799b7efd596bd915d6545359fa9429d71419a7"),
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, digest, dest):
    if not dest.exists() or sha256(dest) != digest:
        print("downloading " + url, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "darkslide-desktop-ci"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
    if sha256(dest) != digest:
        sys.exit("%s: SHA-256 %s, expected %s" % (dest.name, sha256(dest), digest))


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    fetch(*RICOH, out / "gr3_v210.zip")
    with zipfile.ZipFile(out / "gr3_v210.zip") as z:
        name = next(n for n in z.namelist() if n.endswith(FIRMWARE[0]))
        (out / FIRMWARE[0]).write_bytes(z.read(name))
    if sha256(out / FIRMWARE[0]) != FIRMWARE[1]:
        sys.exit("fwdc239b.bin in the zip is not GR III 2.10")

    fetch(*FUJI, out / "fuji-luts.zip")
    converter = Path(__file__).with_name("fuji2gr.py")
    args = []
    with zipfile.ZipFile(out / "fuji-luts.zip") as z:
        for source, title, filename, preset, digest in LUTS:
            src = out / source
            src.write_bytes(z.read(FUJI_DIR + source))
            subprocess.run([sys.executable, "-I", str(converter), str(src), str(out / filename), "--title", title], check=True)
            got = sha256(out / filename)
            if got != digest:
                sys.exit("%s converts to %s on this platform, not %s as on the author's Mac" % (filename, got, digest))
            args.append("--lut=%s=%s" % (out / filename, preset))
    print("inputs ready")
    (out / "selftest-args.txt").write_text("\n".join(["--firmware=%s" % (out / FIRMWARE[0])] + args) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
