"""Start Darkslide on this computer.

    python3 launcher.py [--no-browser]

The server listens on 127.0.0.1 only, on $PORT when that is set and otherwise on
the first free port from 8787 up. It runs on a background thread; this one only
waits until the page's 退出 button (POST /api/quit) or Ctrl+C ends it.
"""
import os
import socket
import sys
import threading
import webbrowser

if sys.version_info < (3, 9):
    sys.exit("Darkslide 需要 Python 3.9 或更新版本")

from darkslide import VERSION  # noqa: E402
from darkslide.server import create_server  # noqa: E402


def free_port(start=8787, tries=20):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":  # same as the server's own bind: a port still in TIME_WAIT counts as free
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("找不到可用端口")


def pick_port(env):
    pinned = env.get("PORT")
    return int(pinned) if pinned else free_port()


def say(text, fallback):
    """Print one line; a console that cannot encode Chinese gets the ASCII `fallback`."""
    try:
        print(text, flush=True)
    except UnicodeEncodeError:  # legacy Windows code pages
        print(fallback, flush=True)


def wait_for(worker):
    """Return once the serving thread has ended. Joining in short slices keeps
    Ctrl+C deliverable to this thread on Windows."""
    while worker.is_alive():
        worker.join(0.5)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    options = list(argv)
    with create_server(pick_port(os.environ)) as httpd:
        address = "http://127.0.0.1:%d/" % httpd.server_address[1]
        worker = threading.Thread(target=httpd.serve_forever, name="darkslide-serve", daemon=True)
        worker.start()
        say("Darkslide GR %s 正在运行，地址 %s" % (VERSION, address),
            "Darkslide GR %s is running at %s" % (VERSION, address))
        say("用完后在网页「设置」里点「退出」，或回到这里按 Ctrl+C。",
            "To stop it: Settings > Quit in the page, or Ctrl+C here.")
        try:
            if "--no-browser" not in options:
                webbrowser.open(address)  # the socket is already listening
            wait_for(worker)
        except KeyboardInterrupt:
            httpd.shutdown()
            worker.join()
    ranges = sys.modules.get("darkslide.lut_ranges")
    if ranges is not None:  # background slider-range work: drop what is still queued instead of finishing it
        ranges.JOBS.stop()
    say("Darkslide GR 已停止，这个窗口可以关了。", "Darkslide stopped.")


if __name__ == "__main__":
    main()
