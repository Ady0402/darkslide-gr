// Preset-name rules; mirrors darkslide/names.py (docs/预设名规范_GRIII_2.10.md).
window.DarkslideNames = {
  check(name, limit) {
    const unsupported = Array.from(new Set(Array.from(name).filter((ch) => ch < "\x20" || ch > "\x7e"))).sort();
    return [
      { rule: "not_empty", ok: name.length > 0, message: "预设名不能为空" },
      { rule: "length", ok: name.length <= limit, message: "长度 " + name.length + " / " + limit },
      { rule: "charset", ok: unsupported.length === 0,
        message: unsupported.length ? "相机字库里没有：" + unsupported.join(" ") : "字符都在相机字库内" },
      { rule: "single_line", ok: !/[\r\n]/.test(name), message: "只能一行" },
      { rule: "no_edge_space", ok: name === name.replace(/^ +| +$/g, ""), message: "首尾不能有空格" },
      { rule: "no_double_space", ok: name.indexOf("  ") < 0, message: "不能有连续空格" },
    ];
  },
  ok(name, limit) {
    return this.check(name, limit).every((c) => c.ok);
  },
};
