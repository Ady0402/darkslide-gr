雙擊就能用的 DARKSLIDE GR：不用安裝 Python、不用開終端機。程式是官方 DARKSLIDE GR {{VERSION}}，原封不動包成 App。
DARKSLIDE GR you can just double-click: no Python, no terminal. It is the official DARKSLIDE GR {{VERSION}}, unchanged, packaged as an app.

> [!IMPORTANT]
> **這是非官方的桌面版**，由 [@Ady0402](https://github.com/Ady0402) 製作，經原作者 [@LiorMoment](https://github.com/LiorMoment) [同意](https://github.com/LiorMoment/darkslide-gr/pull/3)後發布。原作者目前以腳本版為主：如果你習慣用終端機，請使用[官方版](https://github.com/LiorMoment/darkslide-gr/releases)。
> **This is an unofficial desktop build** by @Ady0402, published with the [agreement](https://github.com/LiorMoment/darkslide-gr/pull/3) of the author, @LiorMoment. The official release is the script version: if you are comfortable with a terminal, use the [official release](https://github.com/LiorMoment/darkslide-gr/releases).

> [!WARNING]
> 刷入修改版韌體可能讓相機無法開機甚至永久變磚，也可能失去保修。本專案與理光無關。只支援官方 GR III 2.10／GR IIIx 1.60 原件，請自行從理光官網下載；本版本不附任何韌體檔案。刷機前請照頁面上的說明準備救援卡。
> Flashing modified firmware may brick your camera and void your warranty. Not affiliated with RICOH. Only the official GR III 2.10 / GR IIIx 1.60 files are supported; download them from RICOH yourself. This release contains no firmware files. Prepare a rescue card as the page explains before flashing.

## 下載哪一個 / Which file

| 你的電腦 / Your computer | 檔案 / File |
|---|---|
| Mac（Apple 晶片：M1、M2、M3、M4…） | `Darkslide.GR.{{VERSION}}.arm64.dmg` |
| Mac（Intel） | `Darkslide.GR.{{VERSION}}.amd64.dmg` |
| Windows 10／11（64 位元 / 64-bit） | `Darkslide.GR.Setup.{{VERSION}}.amd64.exe` |

不確定 Mac 是哪一種：點左上角蘋果選單 →「關於這台 Mac」，看「晶片」或「處理器」。
Not sure which Mac: Apple menu → About This Mac → Chip / Processor.

需要 macOS 12 以上。Windows 10 需要 [Microsoft WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)（Windows 11 已內建）。不支援 Windows ARM。
Needs macOS 12 or later. Windows 10 needs the Microsoft WebView2 Runtime (Windows 11 has it). Windows on ARM is not supported.

## 安裝 / Install

**Mac**：打開 dmg，把 DARKSLIDE GR 拖進「應用程式」。這個 App 沒有 Apple 開發者簽章，第一次打開會被擋下：在 App 上按右鍵 →「打開」→「打開」；或到「系統設定 → 隱私權與安全性」，按「強制打開」。之後就能正常雙擊。
**Mac**: open the dmg and drag DARKSLIDE GR into Applications. The app is not signed by an Apple developer, so macOS blocks the first launch: right-click the app → Open → Open, or System Settings → Privacy & Security → Open Anyway.

**Windows**：執行 Setup。如果出現「Windows 已保護您的電腦」，按「其他資訊」→「仍要執行」。App 會裝在你自己的使用者資料夾，不需要系統管理員權限，並建立開始選單和桌面捷徑。
**Windows**: run Setup. If "Windows protected your PC" appears, choose More info → Run anyway. It installs for your user only (no administrator rights) and adds Start menu and desktop shortcuts.

## 和腳本版的差別 / Compared with the script version

- 介面和功能完全相同（同一套頁面），只是開在自己的視窗裡。
  Same page, same features, in a window of its own.
- 和腳本版共用資料夾（Mac：`~/Library/Application Support/Darkslide`；Windows：`%APPDATA%\Darkslide`），兩種版本的工程互通。
  Shares the data folder with the script version; projects work in both.
- 下載的韌體、`.cube`、配方卡會存到「下載」資料夾，並自動在 Finder／檔案總管裡顯示。
  Downloads (firmware, `.cube`, recipe cards) go to your Downloads folder and are shown in Finder / Explorer.
- 「擬合」元件一樣在頁面裡同意後才下載（Unicorn 2.1.4，來自 PyPI）。
  The fitting component is still downloaded only after you agree on the page.
- 關閉視窗或按頁面上的「退出」就完整結束，不會留下背景程式。
  Closing the window or Quit on the page ends everything.

## 遇到問題 / Troubleshooting

- 視窗顯示「無法啟動」：畫面上會附記錄檔內容。記錄檔在 Mac 的 `~/Library/Logs/Darkslide GR/server.log`、Windows 的 `%APPDATA%\Darkslide GR\logs\server.log`。
  If the window says it cannot start, the log is shown there; it lives in the paths above.
- Windows 10 視窗空白：安裝 WebView2 Runtime。
  Blank window on Windows 10: install the WebView2 Runtime.
- 腳本版同時開著也沒關係，桌面版會自動改用下一個連接埠。
  The script version may run at the same time; the app picks the next free port.
- 桌面版本身的問題請到[這裡回報](https://github.com/Ady0402/darkslide-gr/issues)；DARKSLIDE GR 功能本身的問題請到[官方](https://github.com/LiorMoment/darkslide-gr/issues)。
  Problems with the desktop app: report them here; problems with DARKSLIDE GR itself: report them upstream.

## 驗證範圍 / What was tested

在 GitHub Actions 的 macOS（Apple 晶片、Intel）和 Windows 上，每次都自動跑：啟動、匯入官方原件、匯入 4 個 LUT 並改名、調整、換圖示和關機圖、擬合、生成並下載韌體（離線核對全部通過）、退出、強制結束後不留背景程式，以及安裝程式的安裝與啟動。**尚未在真人的 Windows 電腦上手動測試**檔案選擇和拖放；Intel Mac 上擬合加生成約需 5 分鐘，屬正常。
Every build is tested automatically on macOS (Apple silicon, Intel) and Windows in GitHub Actions: start, import the official file, four LUTs renamed, adjustments, icon and shutdown picture, fitting, generating and downloading the firmware (all offline checks pass), quitting, no leftover process after a forced quit, and installing. **Not yet tried by hand on a real Windows PC** (file picker, drag and drop). Fitting and generating take about 5 minutes on an Intel Mac.

## 原始碼與授權 / Source and licences

- DARKSLIDE GR 本體：GPL-2.0-only，原始碼 https://github.com/LiorMoment/darkslide-gr （本版對應官方 `v{{VERSION}}`）。
  DARKSLIDE GR itself: GPL-2.0-only; this build carries the official `v{{VERSION}}` unchanged.
- 桌面版外殼：MIT，原始碼 https://github.com/Ady0402/darkslide-gr/tree/desktop-v{{VERSION}}/desktop 。外殼是獨立程式，只透過本機 HTTP 和 DARKSLIDE GR 溝通。
  The desktop shell: MIT; a separate program that talks to DARKSLIDE GR over local HTTP only.
- App 內附 `DESKTOP_LICENSES.md`（外殼與其 Go 相依套件的授權全文）、`LICENSE`、`THIRD_PARTY_NOTICES.md`，以及內建 Python（PSF）的 `LICENSE.txt`。
  The app includes `DESKTOP_LICENSES.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` and the bundled Python's `LICENSE.txt`.

官方發布新版時，桌面版會在三個平台自動測試通過後跟著更新。
When the official project releases a new version, the desktop app follows once it passes the same tests on all three platforms.
