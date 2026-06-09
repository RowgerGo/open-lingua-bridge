import { invoke } from "@tauri-apps/api/core";

const button = document.querySelector<HTMLButtonElement>("#status-button");
const output = document.querySelector<HTMLPreElement>("#status-output");

button?.addEventListener("click", async () => {
  if (!output) {
    return;
  }
  output.textContent = "检查中...";
  const status = await invoke("get_status");
  output.textContent = JSON.stringify(status, null, 2);
});
