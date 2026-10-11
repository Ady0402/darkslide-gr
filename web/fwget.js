// "No official firmware?" link on the start page: after the user starts the
// download, the hint turns into the next step and the drop zone is outlined.
(function () {
  const link = document.getElementById("fwDownload");
  if (!link) return;
  link.addEventListener("click", () => {
    const line = document.getElementById("fwGet");
    line.classList.add("ready");
    line.textContent = "下载好了？直接把 gr3_v210.zip 拖进来。";
    document.getElementById("drop").classList.add("await");
  });
  // Any import attempt ends the waiting state.
  const input = document.getElementById("fileInput");
  const clear = () => document.getElementById("drop").classList.remove("await");
  input.addEventListener("change", clear);
  document.getElementById("drop").addEventListener("drop", clear);
})();
