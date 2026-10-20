#!/usr/bin/env python3
"""Drive a selftest build of the desktop app through its window, as a user would.

    python3 desktop/scripts/selftest.py <app executable> [--firmware fwdc239b.bin]

The app must be built with `-tags selftest` (see desktop/README.md). Its data goes to
a fresh temporary folder, never the user's own. Without --firmware it checks what
needs no RICOH file: the page loads, a file reaches the server through the page's
import code, a server file and a blob download through the webview's download path,
links leave for the browser, and the page's 退出 ends the app and its server. With
--firmware it also generates a firmware and downloads it through 下载固件.

Exit code 0 when every check passed.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

CONTROL_PORT = 9911
CONTROL = "http://127.0.0.1:%d" % CONTROL_PORT
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (" — " + str(detail) if detail else ""), flush=True)
    return ok


def run_js(code, timeout=180):
    """Run JavaScript in the page; an async function's value is awaited."""
    req = urllib.request.Request(CONTROL + "/" + "ev" + "al", data=code.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        out = json.load(resp)
    if out.get("error"):
        raise RuntimeError(out["error"])
    value = out.get("value")
    return json.loads(value) if isinstance(value, str) and value[:1] in "[{\"" else value


def downloads():
    with urllib.request.urlopen(CONTROL + "/downloads", timeout=5) as resp:
        return json.load(resp)


def wait_download(url_part, before, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        rows = downloads()[before:]
        for row in rows:
            if url_part in row["URL"]:
                return row
        time.sleep(0.25)
    return None


def file_url(path):
    return CONTROL + "/file?path=" + urllib.parse.quote(str(path))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_page(proc, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            return None
        try:
            state = run_js('JSON.stringify({href: location.href, ready: document.readyState, drop: !!document.getElementById("drop")})', timeout=5)
            if state["href"].startswith("http://127.0.0.1:") and state["ready"] == "complete" and state["drop"]:
                return state["href"].rstrip("/")
        except Exception:  # the control channel or the page is not up yet
            pass
        time.sleep(0.25)
    return None


def generate_and_download(origin, firmware, dl_dir):
    """The whole 生成 flow with a real official file, as tested on the author's Mac."""
    out = run_js("""(async () => {
      const blob = await (await fetch(%s)).blob();
      await importFile(new File([blob], %s));
      document.querySelector("#projectPick .btn.primary").click();
      await new Promise((r) => setTimeout(r, 2500));
      const slot = state.template.slots.find((s) => s.rename === "test" && s.name_max);
      return JSON.stringify({imported: document.getElementById("importResult").innerText, slot: slot && slot.no});
    })()""" % (json.dumps(file_url(firmware)), json.dumps(Path(firmware).name)))
    if not check("import the official firmware", out["imported"].startswith("✓"), out["imported"]):
        return
    run_js("""(async () => {
      const name = document.getElementById("nameInput");
      name.value = "Selftest"; name.dispatchEvent(new Event("input", {bubbles: true})); name.dispatchEvent(new Event("change", {bubbles: true}));
      await new Promise((r) => setTimeout(r, 1500));
      document.getElementById("btnGenerate").click();
      await new Promise((r) => setTimeout(r, 1000));
      const d = document.getElementById("preflightDialog");
      if (d.open) [...d.querySelectorAll("button")].find((b) => /继续|繼續|Continue/i.test(b.innerText)).click();
      return "started";
    })()""")
    out = run_js("""(async () => {
      for (let i = 0; i < 600; i++) {
        if (!document.getElementById("doneDownloads").hidden) break;
        if ([...document.querySelectorAll("dialog[open]")].length) break;
        await new Promise((r) => setTimeout(r, 500));
      }
      const a = document.getElementById("dlFirmware");
      return JSON.stringify({ok: !document.getElementById("doneDownloads").hidden, title: document.getElementById("doneTitle").textContent,
        text: document.getElementById("doneText").textContent, href: a.getAttribute("href")});
    })()""", timeout=360)
    if not check("generate a firmware", out["ok"], out["title"] + " " + out["text"]):
        return
    manifest = json.load(urllib.request.urlopen(origin + out["href"].replace("/firmware", "/manifest")))
    before = len(downloads())
    run_js('document.getElementById("dlFirmware").click(); "clicked"')
    row = wait_download(out["href"], before)
    check("download the firmware through 下载固件", row and not row["Err"] and sha256(row["Path"]) == manifest["output_sha256"],
          row and (row["Err"] or row["Path"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("app", help="the app's executable (Darkslide GR.exe, or Contents/MacOS/Darkslide GR)")
    ap.add_argument("--firmware", help="an official fwdc239b.bin for the full generate-and-download check")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="darkslide-selftest-"))
    data, dl_dir = work / "data", work / "downloads"
    data.mkdir()
    dl_dir.mkdir()
    env = dict(os.environ, DARKSLIDE_DATA=str(data), DARKSLIDE_SELFTEST_PORT=str(CONTROL_PORT),
               DARKSLIDE_SELFTEST_DOWNLOADS=str(dl_dir))
    started = time.monotonic()
    proc = subprocess.Popen([args.app], env=env)
    try:
        origin = wait_page(proc)
        if not check("the page loads in the window", origin, "%.1fs" % (time.monotonic() - started)):
            return 1
        print("page at " + origin)

        # A file reaches the server through the page's own import code (what a drop or
        # the file picker hands it). Not a firmware: the server must say so.
        fake = work / "not-firmware.bin"
        fake.write_bytes(b"darkslide selftest " * 64)
        out = run_js("""(async () => {
          const blob = await (await fetch(%s)).blob();
          await importFile(new File([blob], "not-firmware.bin"));
          return document.getElementById("importResult").innerText;
        })()""" % json.dumps(file_url(fake)))
        check("a file goes through the page's import to the server", out.startswith("✕"), out)

        # A server file on a link with download, as 下载固件 is.
        catalog = json.load(urllib.request.urlopen(origin + "/api/film-catalog"))
        films = catalog.get("films") if isinstance(catalog, dict) else catalog
        fid = films[0]["id"]
        path = "/api/film-preview/%s.cube" % urllib.parse.quote(fid)
        expected = hashlib.sha256(urllib.request.urlopen(origin + path).read()).hexdigest()
        before = len(downloads())
        run_js('(() => { const a = document.createElement("a"); a.href = %s; a.download = "selftest-film.cube"; document.body.append(a); a.click(); a.remove(); return "clicked"; })()' % json.dumps(path))
        row = wait_download(path, before)
        check("download a server file from a link", row and not row["Err"] and sha256(row["Path"]) == expected,
              row and (row["Err"] or row["Path"]))

        # A blob with a Chinese name, as 导出 .cube and the recipe card make.
        text = "TITLE \"自测\"\nLUT_3D_SIZE 2\n"
        before = len(downloads())
        run_js("""(() => { const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([%s], {type: "text/plain"})); a.download = "自测 测试.cube";
          a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); return "clicked"; })()""" % json.dumps(text))
        row = wait_download("blob:", before)
        ok = row and not row["Err"] and Path(row["Path"]).name == "自测 测试.cube" and Path(row["Path"]).read_text(encoding="utf-8") == text
        check("download a blob with a Chinese name", ok, row and (row["Err"] or row["Path"]))

        # localStorage keeps what the page remembers.
        out = run_js('(() => { localStorage.setItem("darkslide.selftest", "記得"); return localStorage.getItem("darkslide.selftest"); })()')
        check("localStorage works", out == "記得", out)

        # A link to another site leaves for the browser; the window stays on the app.
        run_js('(() => { const a = document.createElement("a"); a.href = "https://example.com/"; document.body.append(a); a.click(); a.remove(); return "clicked"; })()')
        time.sleep(1.5)
        out = run_js("location.href")
        check("external links leave the window alone", out.rstrip("/") == origin, out)

        if args.firmware:
            generate_and_download(origin, args.firmware, dl_dir)

        # The page's 退出 ends the server, and with it the app.
        server = urllib.parse.urlparse(origin).port
        run_js('document.getElementById("btnQuit").click(); "clicked"')
        try:
            code = proc.wait(timeout=20)
            check("退出 quits the app", True, "exit code %d" % code)
        except subprocess.TimeoutExpired:
            check("退出 quits the app", False, "still running after 20s")
        time.sleep(1)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/" % server, timeout=2)
            check("the server stopped with the app", False, "still answering")
        except OSError:
            check("the server stopped with the app", True)
    finally:
        if proc.poll() is None:
            proc.kill()
    failed = [name for name, ok in results if not ok]
    print("\n%d passed, %d failed" % (len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
