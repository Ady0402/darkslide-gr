# DARKSLIDE GR 桌面版（MyGo 外壳，原型）

用 [MyGo](https://mygo.egoist.dev/) 把现有的 DARKSLIDE GR 包成 macOS 和 Windows 桌面应用。Python 程序一行不改：应用自带一份独立的 Python，启动时在 127.0.0.1 上运行 `launcher.py --no-browser`，再用系统 WebView（macOS 的 WKWebView、Windows 的 WebView2）打开页面。

- 用户不用自己装 Python，双击即可。
- 数据文件夹与脚本版相同（`~/Library/Application Support/Darkslide`、`%APPDATA%\Darkslide`），两种方式可以混用。
- 端口沿用 8787 起的前 20 个，页面来源保持不变，`localStorage` 里记住的设置照常有效。
- 页面里的「退出」会结束整个应用；关闭窗口或退出应用时，会先按同样方式请服务停止，3 秒内没停就强制结束。Windows 上服务进程绑在 Job Object 里，应用崩溃或被任务管理器结束时也会一起结束。
- 理光官网等外部链接用系统浏览器打开。下载的文件存到「下载」文件夹，并在 Finder 或资源管理器里显示。

## 外壳替页面补上的几处

页面代码不改；外壳用预加载脚本把下面几类请求交给 Go（只对本机服务的页面开放）：

- **耗时请求**（拟合、生成并核对等）：WebKit 的请求 60 秒没有回应就会放弃（Intel Mac 会遇到），改由 Go 发送，等到服务回应为止。
- **Windows 的下载**：WebView2 不下载 `blob:` 链接（导出 .cube、配方卡），同一页面也只放行一次没有用户点击的下载。在 Windows 上，带 `download` 的链接改由 Go 写进「下载」文件夹。设置 `DARKSLIDE_DOWNLOAD_BRIDGE=1` 可以在其他系统上测试这一路径。

## 构建

需要 Go 1.27 或更新版本。在 macOS 上打包 Windows 安装程序还需要 NSIS（`brew install makensis`）。

```sh
cd desktop
python3 scripts/fetch_python.py          # 下载并核对 python-build-standalone（固定版本和 SHA-256）
LC_ALL=en_US.UTF-8 go tool mygo build -platform darwin/arm64,darwin/amd64,windows/amd64
```

产物在 `dist/<平台>/`：macOS 是 `.app` 和 `.dmg`，Windows 是 `Darkslide GR Setup <版本> amd64.exe`（按用户安装，不需要管理员权限）。Homebrew 的 makensis 在没有 UTF-8 locale 时会崩溃（`std::bad_alloc`），所以要加 `LC_ALL`。

开发时用 `go tool mygo dev`，程序文件直接取自仓库。用 `DARKSLIDE_PYTHON` 可以改用别的 Python。

## 平台

| 平台 | Python | 拟合（Unicorn） |
|---|---|---|
| macOS Apple 芯片 | darwin-arm64 | 支持 |
| macOS Intel | darwin-amd64 | 支持 |
| Windows x64 | windows-amd64 | 支持 |

Windows 10 需要安装 WebView2 Runtime，Windows 11 已经自带。Unicorn 没有 Windows ARM64 版本，所以不提供这个平台。

## 自测构建

`-tags selftest` 会加入一个只监听 127.0.0.1 的控制通道（见 `selftest.go`）：可以在页面里执行 JavaScript、读取已完成的下载，并把本机文件交给页面，相当于拖入文件。正式构建不包含这个通道。

```sh
GOFLAGS=-tags=selftest go tool mygo build -platform darwin/arm64 -skip-dmg -o build-selftest
open -n --env DARKSLIDE_DATA=/tmp/ds --env DARKSLIDE_SELFTEST_PORT=9911 \
  --env DARKSLIDE_SELFTEST_DOWNLOADS=/tmp/dl "build-selftest/darwin-arm64/Darkslide GR.app"
```
