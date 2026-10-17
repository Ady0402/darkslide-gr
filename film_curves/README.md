# 胶片曲线（film_curves）

本文件夹存放 DARKSLIDE GR 胶片模拟用的曲线数据。它的许可与 DARKSLIDE GR 程序代码（GPL-2.0-only）不同，单独适用 **CC BY-SA 4.0**。

## 来源与署名

Derived from **spektrafilm** by **Andrea Volpato**
https://github.com/andreavolpato/spektrafilm
Licensed CC BY-SA 4.0（全文见本目录 `SPEKTRAFILM_LICENSE.txt`，未作改动）
Modified by LiorMoment（改动内容见 `CHANGELOG.txt`）

本文件夹里的曲线由 spektrafilm 的胶片与相纸数据导出 LUT 后，再拟合成 GR III 机内可用的设置。DARKSLIDE GR 只使用这些数据，没有使用 spektrafilm 的程序代码。

## 已接入的相机参数

`upstream_gr3_fits/` 保留 gr3-film-mods 固定提交 `04d5d5dd6e85d80089c6200bd0f0de5fff2d658f` 的8份现成拟合原文，`camera/` 为 LiorMoment 转换的 GR III 2.10 参数。来源：[idontknownihil/gr3-film-mods](https://github.com/idontknownihil/gr3-film-mods)。原始数据作者 Andrea Volpato，第一次拟合修改者 idontknownihil，再由 LiorMoment 做 Q13 量化、字段转换及来源记录；全部仍为 CC BY-SA 4.0。逐文件原文及转换后 SHA、胶片与相纸见 `camera_profiles_manifest.json`，修改记录见 CHANGELOG.txt。

已提供 Portra400、Gold200、Ektar100、Pro400H、UltraMax400、Vision3 250D（5207）、Vision3 500T（5219）和 X-Tra400/Portra Endura。最后一卷的id为 `xtra400_portraendura`，与 Crystal Archive 相纸目标不同，不能悄悄代替该目标。采用不依赖色相分区的拟合版本；没有把较新的分区拟合删掉一层后当成等效版本。

**在原厂范围内拟合（2026-10-14 起）**：拟合时，前矩阵系数、每行绝对值之和、曲线陡度都限制在运行时从官方原件读出的理光原厂预设范围内，不再事后拒绝。Ektar 100、X-Tra 400（原为 gr3-film-mods 的拟合）、5213、Portra 800 推 1 和推 2 档因此由 DARKSLIDE GR 在范围内重新拟合；上游那两份拟合仍保留在 `upstream_gr3_fits/`，清单中标为 `"in_use": false` 并写明原因。

**DARKSLIDE GR 自己拟合的 8 卷（2026-10-14）**：Portra 160、Portra 800、Portra 800 推 1 档、Portra 800 推 2 档、C200、Vision3 50D（5203）、Vision3 200T（5213）、Verita 200D。由 LiorMoment 用 DARKSLIDE GR 的拟合器，从 spektrafilm v0.3.4 的 sRGB→sRGB 33³ 导出直接拟合成 GR III 2.10 参数（先按 RGB 拟合，再按 CIEDE2000 做感知精调；拟合算法移植自 gr3-film-mods，MIT）；拟合时用的相机基础曲线在运行时从官方原件读出，没有存进这里。原始数据作者 Andrea Volpato，修改者 LiorMoment，仍为 CC BY-SA 4.0。逐卷来源 SHA、近似程度与色差见 `camera_profiles_darkslide_fits.json`；这些参数的 `provenance.kind` 为 `darkslide_fit`。和上面 8 卷一样，都没有实拍验证。

这些是可读取的实验相机参数；未验证我方相机效果，基础曝光模型7.8仍是上游假设。数据就绪不代表固件导出开放；也不表示16卷预览目标都已有对应相机参数。

**导出后设定白点（2026-10-15，现行）**：spektrafilm 的导出把相纸本身的白（约 0.78–0.85）原样保留，放到屏幕上整体偏暗、白发灰。现在 16 卷全部改为：spektrafilm v0.3.4 sRGB→sRGB 33³、中灰以上 2.47 档（相纸反差不变），导出后把相纸白定到 0.97（线性光整体乘同一系数，相当于扫描时定白点）。定白点是我们自己写的后处理，没有改 spektrafilm 的文件。16 卷的预览和相机参数都由 DARKSLIDE GR 在原厂范围内重新拟合，`provenance.export` 写明了设置。gr3-film-mods 的现成拟合对应未定白点的导出，不再使用，原文仍保留在 `upstream_gr3_fits/`，清单里标为 `"in_use": false` 并写明原因。

## 预览 LUT 与目录（`preview/`、`catalog.json`）

`preview/*.cube` 是界面里给样张做近似预览用的 17³ LUT，**不是相机数据**。由 spektrafilm v0.3.4 的导出工具按 sRGB→sRGB、中灰以上 2.47 档导出 33³，定白点到 0.97 后再隔点取成 17³，数值保留 4 位小数；每卷的胶片和相纸与 `camera/` 里同名数据的拟合目标相同。原始数据作者 Andrea Volpato，由 LiorMoment 导出、定白点和重采样，仍为 CC BY-SA 4.0。预览只表示胶片目标的大致样子；相机里的实际效果以写入后的实拍为准。

`catalog.json` 列出界面里可选的内置胶片，包括显示名、胶片、相纸和预览文件。电影卷用片号命名：5207 是 Vision3 250D，5219 是 Vision3 500T。

## 你可以

- 自由使用、分享、修改本文件夹里的数据，个人和商业用途都可以。
- 分享或修改时请保留上面的署名和许可，修改后的数据仍须使用 CC BY-SA 4.0，并在 `CHANGELOG.txt` 里写明改了什么、由谁改的。

## 说明

- 文件名和界面中出现的胶片名称只用来说明效果的灵感来源，这些名称是各自权利人的商标。本数据不是厂商出品，也不是对胶片的精确复刻，只是在相机设置范围内的近似效果。
- 用 DARKSLIDE GR 拍出的照片完全属于你，不受本许可约束。
