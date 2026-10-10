"""Start Darkslide: pick a free port near 8787, serve, open the browser."""
import os
import socket
import sys
import threading
import webbrowser

if sys.version_info < (3, 9):
    sys.exit("Darkslide 需要 Python 3.9 或更新版本")

from darkslide import VERSION  # noqa: E402
from darkslide.server import serve  # noqa: E402


def free_port(start=8787, tries=20):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("找不到可用端口")


def main():
    no_browser = "--no-browser" in sys.argv
    port = int(os.environ["PORT"]) if os.environ.get("PORT") else free_port()
    httpd = serve(port)
    url = "http://127.0.0.1:%d/" % port
    try:
        print("Darkslide GR %s 已启动：%s" % (VERSION, url))
        print("关闭本窗口或按 Ctrl+C 停止。")
    except UnicodeEncodeError:  # legacy Windows consoles
        print("Darkslide %s running at %s (Ctrl+C to stop)" % (VERSION, url))
    if not no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            print("Darkslide GR 已退出。")
        except UnicodeEncodeError:
            print("Darkslide stopped.")


if __name__ == "__main__":
    main()
