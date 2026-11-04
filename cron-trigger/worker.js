// 準時觸發 GitHub Actions 的 daily.yml。
//
// GitHub Actions 自己的 cron 會延遲數小時、甚至整個被丟掉；Cloudflare 的
// Cron Trigger 基本上分鐘級準時，所以改由這裡在固定時間打 workflow_dispatch。
//
// 每次觸發做兩件事：
//   1. 先 enable workflow —— 公開 repo 60 天沒 commit，GitHub 會自動停用排程，
//      停用後 dispatch 也會失敗。enable 是冪等的，本來就啟用也不影響。
//   2. dispatch，帶 skip_if_done=true —— 台灣當天已成功過就由 workflow 自己跳過，
//      所以這裡排多個時段當重試也不會重複燒額度。

const API = "https://api.github.com";

async function trigger(env) {
  const repo = env.GH_REPO;
  const workflow = env.GH_WORKFLOW || "daily.yml";
  const ref = env.GH_REF || "main";
  const base = `${API}/repos/${repo}/actions/workflows/${workflow}`;
  const headers = {
    Authorization: `Bearer ${env.GH_TOKEN}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "ainews-cron-trigger",
  };

  const enable = await fetch(`${base}/enable`, { method: "PUT", headers });
  if (!enable.ok) {
    // 不中止：enable 失敗不代表 dispatch 一定失敗，把原因留在 log
    console.warn(`enable ${enable.status}: ${await enable.text()}`);
  }

  const res = await fetch(`${base}/dispatches`, {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({ ref, inputs: { skip_if_done: "true" } }),
  });
  if (!res.ok) {
    // 丟出去讓 Cloudflare 把這次 cron 記成失敗，Dashboard 看得到
    throw new Error(`dispatch ${res.status}: ${await res.text()}`);
  }
  console.log(`dispatched ${repo} ${workflow}@${ref}`);
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(trigger(env));
  },
};

export { trigger };
