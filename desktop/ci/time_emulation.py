#!/usr/bin/env python3
"""Time DARKSLIDE GR's read-only camera emulation on this computer, for CI.

    <bundled python> desktop/ci/time_emulation.py <fwdc239b.bin> <report.json>

Runs with the Python the desktop app bundles, from a checkout, on a fresh data
folder. It installs the fitting component (Unicorn 2.1.4 from PyPI, as the app
does), then times what a fit waits on: base_curve(), the worker subprocess the
server runs with its 60-second limit, and the same emulation inside this process.
Nothing in darkslide/ is changed; only this process lifts the limit, to see how
long the run really takes, up to LIMIT. self_check() then says whether the values
match the reference the project ships.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIMIT = 1800  # seconds, instead of the server's 60

sys.path.insert(0, str(REPO))
os.environ["DARKSLIDE_DATA"] = tempfile.mkdtemp(prefix="darkslide-timing-")


def main():
    firmware, out = Path(sys.argv[1]), Path(sys.argv[2])
    from darkslide import base_curve, fitting_setup
    from darkslide.paths import data_root

    report = {"platform": sys.platform, "machine": platform.machine(), "processor": platform.processor(),
              "cpus": os.cpu_count(), "python": sys.version.split()[0], "python_executable": sys.executable,
              "server_limit_seconds": 60}
    t = time.monotonic()
    report["fitting_setup"] = fitting_setup.install(data_root())
    report["install_seconds"] = round(time.monotonic() - t, 2)

    run = subprocess.run

    def unlimited(*args, **kwargs):
        if kwargs.get("timeout") == 60:
            kwargs["timeout"] = LIMIT
        return run(*args, **kwargs)
    subprocess.run = unlimited  # this process only: base_curve calls subprocess.run

    t = time.monotonic()
    try:
        contract = base_curve.base_curve(firmware)
        report["base_curve_seconds"] = round(time.monotonic() - t, 2)
    except Exception as error:  # still say how long it ran
        report["base_curve_seconds"] = round(time.monotonic() - t, 2)
        report["base_curve_error"] = str(error)
        contract = None

    if contract is not None:
        try:
            check = fitting_setup.self_check(firmware, contract=contract, root=data_root())
            report["self_check"] = check
        except Exception as error:
            report["self_check"] = {"ok": False, "error": str(error)}

        # The same emulation without the worker subprocess around it.
        import hashlib
        raw = firmware.read_bytes()
        t = time.monotonic()
        base_curve._compute(raw, hashlib.sha256(raw).hexdigest(), contract["backend"])
        report["in_process_seconds"] = round(time.monotonic() - t, 2)

    over = report["base_curve_seconds"] > 60
    report["verdict"] = ("over the server's 60 s limit: fitting fails here" if over
                         else "within the server's 60 s limit")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("platform", "machine", "processor", "cpus", "install_seconds",
                                                  "base_curve_seconds", "in_process_seconds", "verdict")}, ensure_ascii=False))
    if "self_check" in report:
        print("self check:", report["self_check"].get("ok"), report["self_check"].get("error", ""))
    if "base_curve_error" in report:
        print("base_curve error:", report["base_curve_error"])


if __name__ == "__main__":
    main()
