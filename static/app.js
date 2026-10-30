/* 个人AI知识库 - 前端逻辑 */
const API = (path, opts = {}) => {
  const { body, ...rest } = opts;
  return fetch(path, {
    ...rest,
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + localStorage.getItem("token") },
    body: body ? JSON.stringify(body) : undefined,
  }).then(async r => {
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "请求失败");
    return data;
  });
};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const libShort = l => (l || "").replace("库", "");

let token = localStorage.getItem("token");
let currentLibrary = null;

/* ---------- 认证 ---------- */
async function initAuth() {
  if (token) {
    try { await API("/api/settings"); showApp(); return; }
    catch { localStorage.removeItem("token"); token = null; }
  }
  showLogin();
}
function showLogin() {
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("app-view").classList.add("hidden");
}
function showApp() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("app-view").classList.remove("hidden");
  const isDev = localStorage.getItem("is_dev") === "1";
  const phoneText = localStorage.getItem("phone");
  document.getElementById("user-phone").textContent = isDev ? "🔧 " + phoneText : phoneText;
  loadDashboard();
}

document.getElementById("send-code").onclick = async () => {
  const rawPhone = document.getElementById("login-phone").value.trim();
  // 自动提取数字（支持 +86、空格、横线等格式）
  let phone = rawPhone.replace(/[^\d]/g, "");
  // 去掉 86 国家码前缀
  if (phone.length === 13 && phone.startsWith("86")) phone = phone.slice(2);
  if (!/^1\d{10}$/.test(phone)) { setErr("请输入正确的手机号（11位数字）"); return; }
  try {
    const r = await API("/api/send-code", { method: "POST", body: { phone } });
    if (r.dev_code) {
      document.getElementById("login-devtip").textContent = "开发模式验证码：" + r.dev_code + "（5分钟内有效）";
    } else {
      document.getElementById("login-devtip").textContent = "验证码已发送，请查收短信。";
    }
    setErr("");
  } catch (e) { setErr(e.message); }
};
document.getElementById("login-btn").onclick = async () => {
  const rawPhone = document.getElementById("login-phone").value.trim();
  let phone = rawPhone.replace(/[^\d]/g, "");
  if (phone.length === 13 && phone.startsWith("86")) phone = phone.slice(2);
  const code = document.getElementById("login-code").value.trim();
  try {
    const r = await API("/api/login", { method: "POST", body: { phone, code } });
    token = r.token;
    localStorage.setItem("token", token);
    localStorage.setItem("phone", phone);
    setErr("");
    showApp();
  } catch (e) { setErr(e.message); }
};
document.getElementById("dev-login-btn").onclick = async () => {
  try {
    const r = await API("/api/dev-login", { method: "POST" });
    token = r.token;
    localStorage.setItem("token", token);
    localStorage.setItem("phone", r.user.phone);
    localStorage.setItem("is_dev", "1");
    setErr("");
    showApp();
  } catch (e) { setErr(e.message); }
};
document.getElementById("logout").onclick = async () => {
  try { await API("/api/logout", { method: "POST" }); } catch {}
  localStorage.removeItem("token");
  localStorage.removeItem("phone");
  token = null;
  showLogin();
};
function setErr(m) { document.getElementById("login-err").textContent = m; }

/* ---------- 导航 ---------- */
document.querySelectorAll(".nav-btn").forEach(btn => {
  btn.onclick = () => go(btn.dataset.page);
});
function go(page) {
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.page === page));
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  document.getElementById("page-" + page).classList.add("active");
  const loaders = { dashboard: loadDashboard, capture: loadCaptures, library: loadLibrary, ask: loadAsk, graph: loadGraph, learn: loadLearn, agents: loadAgents, review: loadReviews, meta: loadMeta, profile: loadProfile, settings: loadSettings };
  loaders[page]?.();
}

/* ---------- 工作台 ---------- */
async function loadDashboard() {
  const [meta, actions, captures] = await Promise.all([
    API("/api/meta"), API("/api/actions"), API("/api/captures")
  ]);
  const g = meta.growth;
  document.getElementById("stat-cards").textContent = g.card_count;
  document.getElementById("stat-quality").textContent = g.avg_quality;
  document.getElementById("stat-streak").textContent = g.review_streak;
  document.getElementById("stat-fix").textContent = g.corrections_fixed;
  document.getElementById("dash-actions").innerHTML = actions.actions.length
    ? actions.actions.slice(0, 10).map(a => `<div class="list-item"><div class="li-title">${esc(a.content)}</div></div>`).join("")
    : '<div class="list-item"><div class="li-sub">暂无行动项。采集内容并蒸馏后，AI 会自动提取。</div></div>';
  document.getElementById("dash-captures").innerHTML = captures.captures.length
    ? captures.captures.slice(0, 5).map(c => `<div class="list-item"><div class="li-title">${esc(c.title || c.source_type)} <span class="tag">${esc(c.source_type)}</span>${c.status === "pending" ? '<span class="tag" style="background:#fef3c7;color:#b45309">待蒸馏</span>' : ""}</div><div class="li-sub">${esc(c.created_at ? new Date(c.created_at * 1000).toLocaleString() : "")}</div></div>`).join("")
    : '<div class="list-item"><div class="li-sub">还没有采集内容，点击「+ 采集内容」开始。</div></div>';
}

/* ---------- 采集 ---------- */
const capTabs = ["note", "link", "file", "video"];
document.querySelectorAll("[data-cap]").forEach(t => {
  t.onclick = () => {
    document.querySelectorAll("[data-cap]").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    capTabs.forEach(k => document.getElementById("cap-" + k).classList.toggle("hidden", k !== t.dataset.cap));
  };
});
document.getElementById("cap-submit").onclick = async () => {
  const active = document.querySelector("[data-cap].active").dataset.cap;
  try {
    if (active === "link") {
      await API("/api/capture/fetch", { method: "POST", body: { url: document.getElementById("cap-url").value.trim() } });
    } else if (active === "file") {
      const file = document.getElementById("cap-file-input").files[0];
      if (!file) throw new Error("请选择文件");
      const text = await file.text();
      await API("/api/capture", { method: "POST", body: { source_type: "file", title: file.name, raw_content: text } });
    } else if (active === "video") {
      const text = document.getElementById("cap-video-text").value.trim();
      if (!text) throw new Error("请粘贴转录文稿");
      await API("/api/capture", { method: "POST", body: { source_type: "video", source_url: document.getElementById("cap-video-url").value.trim(), title: "视频文稿", raw_content: text } });
    } else {
      const content = document.getElementById("cap-content").value.trim();
      if (!content) throw new Error("内容不能为空");
      await API("/api/capture", { method: "POST", body: { source_type: "note", title: document.getElementById("cap-title").value.trim(), raw_content: content } });
    }
    document.getElementById("cap-msg").textContent = "已保存，去「采集」列表点击蒸馏。";
    loadCaptures();
  } catch (e) { document.getElementById("cap-msg").textContent = e.message; }
};
async function loadCaptures() {
  const { captures } = await API("/api/captures");
  document.getElementById("capture-list").innerHTML = captures.length
    ? captures.map(c => `<div class="list-item">
        <div class="li-title">${esc(c.title || c.source_type)} <span class="tag">${esc(c.source_type)}</span>${c.status === "pending" ? '<span class="tag" style="background:#fef3c7;color:#b45309">待蒸馏</span>' : '<span class="tag" style="background:#dcfce7;color:#16a34a">已蒸馏</span>'}</div>
        <div class="li-body">${esc((c.raw_content || "").slice(0, 150))}…</div>
        ${c.status === "pending" ? `<div class="li-ops"><button class="btn small primary" onclick="distill(${c.id})">蒸馏为知识卡片</button></div>` : ""}
      </div>`).join("")
    : '<div class="list-item"><div class="li-sub">暂无待蒸馏内容。</div></div>';
}
async function distill(id) {
  const r = await API("/api/distill", { method: "POST", body: { capture_id: id } });
  const cards = (r.cards || []).map(c => `- ${c.title}（${c.library}，质量 ${c.quality_score}）`).join("\n");
  alert("蒸馏完成（" + (r.mode === "ai" ? "AI" : "规则") + "模式）：\n\n" + (cards || "无新卡片") + (r.actions?.length ? "\n\n行动项：\n" + r.actions.join("\n") : ""));
  loadCaptures();
}

/* ---------- 知识库 ---------- */
document.getElementById("lib-search-btn").onclick = () => loadLibrary();
document.getElementById("lib-search").onkeydown = e => { if (e.key === "Enter") loadLibrary(); };
async function loadLibrary() {
  const q = document.getElementById("lib-search").value.trim();
  const { cards } = await API("/api/cards" + (q ? "?q=" + encodeURIComponent(q) : "") + (currentLibrary ? "&library=" + encodeURIComponent(currentLibrary) : ""));
  document.getElementById("card-list").innerHTML = cards.length
    ? cards.map(c => `<div class="card-item">
        <div class="c-lib">${esc(libShort(c.library))}</div>
        <div class="c-title">${esc(c.title)}</div>
        <div class="c-body">${esc(c.content)}</div>
        <div class="c-meta"><span>${esc(c.tags)}</span><span class="quality q${Math.round(c.quality_score)}">${c.quality_score}分</span></div>
      </div>`).join("")
    : '<div class="list-item"><div class="li-sub">没有匹配的卡片。</div></div>';
  if (!document.getElementById("lib-filters").childElementCount) {
    const libs = ["00-灵感库", "01-项目库", "02-资产库", "03-资源库", "04-归档库", "05-Skills", "06-Wiki", "07-原子库"];
    document.getElementById("lib-filters").innerHTML = `<button class="filter-chip active" data-lib="">全部</button>` + libs.map(l => `<button class="filter-chip" data-lib="${l}">${l}</button>`).join("");
    document.querySelectorAll(".filter-chip").forEach(chip => {
      chip.onclick = () => {
        document.querySelectorAll(".filter-chip").forEach(x => x.classList.remove("active"));
        chip.classList.add("active");
        currentLibrary = chip.dataset.lib;
        loadLibrary();
      };
    });
  }
}

/* ---------- 问答 ---------- */
function loadAsk() { document.getElementById("chat-log").innerHTML = ""; loadAskMode(); }
async function loadAskMode() {
  try {
    const r = await API("/api/settings");
    document.getElementById("ask-mode").textContent = "当前模式：" + (r.ai_enabled ? "AI 智能问答" : "规则模式（配置 AI 接口后升级）");
  } catch {}
}
/* 问答功能绑定在底部（RAG 版本） */

/* ---------- 复盘 ---------- */
document.getElementById("review-ai").onclick = () => {
  document.getElementById("review-input").value =
    "方法：今天用AI蒸馏了一篇公众号文章\n动作：采集3条内容，蒸馏成5张卡片，写了一条复盘\n结果：花了40分钟，卡片质量分平均4.2\n卡点：不确定这些卡片以后能不能用上";
};
document.getElementById("review-submit").onclick = async () => {
  const content = document.getElementById("review-input").value.trim();
  if (!content) { document.getElementById("review-msg").textContent = "先写复盘内容"; return; }
  try {
    const r = await API("/api/review", { method: "POST", body: { content } });
    document.getElementById("review-msg").textContent = "复盘已保存，已自动沉淀为知识卡片。";
    const box = document.getElementById("review-analysis");
    box.classList.remove("hidden");
    box.textContent = "【AI 分析】\n" + r.analysis;
    loadReviews();
  } catch (e) { document.getElementById("review-msg").textContent = e.message; }
};
async function loadReviews() {
  const { reviews } = await API("/api/reviews");
  document.getElementById("review-history").innerHTML = reviews.length
    ? reviews.map(r => `<div class="list-item"><div class="li-title">${esc(r.date)}</div><div class="li-body">${esc(r.content.slice(0, 120))}</div></div>`).join("")
    : '<div class="list-item"><div class="li-sub">还没有复盘记录。姜胡说喊了六年：每天写点什么。</div></div>';
}

/* ---------- 元认知 ---------- */
document.getElementById("corr-submit").onclick = async () => {
  const error = document.getElementById("corr-error").value.trim();
  if (!error) return;
  await API("/api/correction", { method: "POST", body: { error, context: document.getElementById("corr-context").value.trim(), lesson: document.getElementById("corr-lesson").value.trim() } });
  document.getElementById("corr-error").value = "";
  document.getElementById("corr-context").value = "";
  document.getElementById("corr-lesson").value = "";
  loadMeta();
};
async function loadMeta() {
  const [meta, corrections] = await Promise.all([API("/api/meta"), API("/api/corrections")]);
  const g = meta.growth;
  document.getElementById("meta-reviews").textContent = g.review_days;
  document.getElementById("meta-streak").textContent = g.review_streak;
  document.getElementById("meta-open").textContent = g.corrections_open;
  document.getElementById("meta-fixed").textContent = g.corrections_fixed;
  document.getElementById("correction-list").innerHTML = corrections.corrections.length
    ? corrections.corrections.map(c => `<div class="list-item">
        <div class="li-title">${esc(c.error)} <span class="tag" style="${c.status === "open" ? "background:#fef3c7;color:#b45309" : "background:#dcfce7;color:#16a34a"}">${c.status === "open" ? "待改" : "已改"}</span></div>
        ${c.context ? `<div class="li-sub">背景：${esc(c.context)}</div>` : ""}
        ${c.lesson ? `<div class="li-body">教训：${esc(c.lesson)}</div>` : ""}
        ${c.status === "open" ? `<div class="li-ops"><button class="btn small primary" onclick="fixCorr(${c.id})">标记已改</button></div>` : ""}
      </div>`).join("")
    : '<div class="list-item"><div class="li-sub">错题本为空。自我改错是姜胡说体系里唯一能"终止错误延续"的功能。</div></div>';
  const mineBias = new Set(meta.bias_notes.map(n => n.title));
  document.getElementById("bias-list").innerHTML = meta.bias_library.map(b => {
    const mine = meta.bias_notes.find(n => n.title === b.split("：")[0]);
    return `<div class="bias-item ${mine ? "mine" : ""}"><div><div class="b-name">${esc(b)}</div></div>${mine ? `<div class="b-desc">${esc(mine.content)}</div>` : '<button class="btn small" onclick="claimBias(this,' + JSON.stringify(b.split("：")[0]) + ')">认领</button>'}</div>`;
  }).join("");
  document.getElementById("model-list").innerHTML = meta.model_library.map(m => {
    const mine = meta.model_notes.find(n => n.title === m.split("：")[0]);
    return `<div class="bias-item ${mine ? "mine" : ""}"><div><div class="b-name">${esc(m)}</div></div>${mine ? `<div class="b-desc">${esc(mine.content)}</div>` : ""}</div>`;
  }).join("");
}
function claimBias(btn, name) {
  const content = prompt("这个偏差你具体怎么犯的？（写下自己的真实表现，越具体越好）", "");
  if (content) API("/api/meta/bias", { method: "POST", body: { title: name, content } }).then(loadMeta);
}
function fixCorr(id) { API("/api/correction/fix", { method: "POST", body: { id } }).then(loadMeta); }
document.getElementById("bias-add-toggle").onclick = () => document.getElementById("bias-add").classList.toggle("hidden");
document.getElementById("model-add-toggle").onclick = () => document.getElementById("model-add").classList.toggle("hidden");
document.getElementById("bias-add").onclick = async () => {
  await API("/api/meta/bias", { method: "POST", body: { title: document.getElementById("bias-title").value.trim(), content: document.getElementById("bias-content").value.trim() } });
  loadMeta();
};
document.getElementById("model-add").onclick = async () => {
  await API("/api/meta/model", { method: "POST", body: { title: document.getElementById("model-title").value.trim(), content: document.getElementById("model-content").value.trim() } });
  loadMeta();
};

/* ---------- 档案 ---------- */
async function loadProfile() {
  const { content } = await API("/api/profile");
  document.getElementById("profile-input").value = content;
}
document.getElementById("profile-save").onclick = async () => {
  const content = document.getElementById("profile-input").value.trim();
  if (!content) { document.getElementById("profile-msg").textContent = "档案不能为空"; return; }
  await API("/api/profile", { method: "POST", body: { content } });
  document.getElementById("profile-msg").textContent = "档案已保存。";
};
document.getElementById("profile-ai").onclick = async () => {
  const raw = document.getElementById("profile-input").value.trim();
  if (!raw) { document.getElementById("profile-msg").textContent = "先写一段自述再点 AI 梳理"; return; }
  const r = await API("/api/profile", { method: "POST", body: { content: raw, raw_self: raw } });
  const box = document.getElementById("profile-ai-out");
  box.classList.remove("hidden");
  box.textContent = r.ai_help || "（未配置AI接口）已保存自述。可稍后再点此按钮获得结构化档案建议。";
  document.getElementById("profile-msg").textContent = "档案已保存。";
};

/* ---------- 设置 ---------- */
async function loadSettings() {
  const r = await API("/api/settings");
  document.getElementById("set-status").textContent = r.ai_enabled ? "✅ AI 接口已启用" : "⚠️ 规则模式（未配置 AI 接口，功能受限）";
  document.getElementById("set-base").value = localStorage.getItem("set-base") || "";
  document.getElementById("set-model").value = localStorage.getItem("set-model") || "gpt-4o-mini";
}
document.getElementById("set-save").onclick = async () => {
  const body = {
    base_url: document.getElementById("set-base").value.trim(),
    model: document.getElementById("set-model").value.trim(),
    api_key: document.getElementById("set-key").value.trim(),
  };
  const r = await API("/api/settings/save", { method: "POST", body });
  document.getElementById("set-msg").textContent = "保存成功，AI 模式：" + (r.ai_enabled ? "已启用" : "未启用");
  localStorage.setItem("set-base", body.base_url);
  localStorage.setItem("set-model", body.model);
};

/* ---------- 运维看板 ---------- */
async function loadOps() {
  const r = await API("/api/ops/dashboard");
  renderOpsDigest(r.digests);
  renderOpsTasks(r.task_runs);
  renderOpsSources(r.sources);
  renderOpsExpiry(r.expired_flags);
  renderOpsVersions(r.snapshots);
  renderOpsChanges(r.change_logs);
}
function renderOpsDigest(digests) {
  const el = document.getElementById("ops-digest");
  if (!digests || !digests.length) { el.innerHTML = '<div class="li-sub">暂无摘要</div>'; return; }
  const d = digests[0];
  el.innerHTML = `<div class="li-title">${esc(d.date)}</div>
    <div class="li-body">采集源：${d.total_sources}（已抓取${d.sources_fetched}）| 新增：${d.new_items} | 重复：${d.duplicate_items} | 过期：${d.expired_items} | 优化：${d.optimizations} | 变更：${d.changes_count}</div>`;
}
function renderOpsTasks(runs) {
  const el = document.getElementById("ops-tasks");
  if (!runs || !runs.length) { el.innerHTML = '<div class="li-sub">暂无运行记录</div>'; return; }
  el.innerHTML = runs.map(r => `<div class="li-title">${esc(r.task_name)} <span class="tag" style="${r.status==='success'?'background:#dcfce7;color:#16a34a':r.status==='error'?'background:#fee2e2;color:#dc2626':'background:#fef3c7;color:#b45309'}">${r.status}</span></div>
    <div class="li-sub">${r.summary}</div>`).join("");
}
function renderOpsSources(sources) {
  const el = document.getElementById("ops-sources");
  if (!sources || !sources.length) { el.innerHTML = '<div class="li-sub">暂无采集源</div>'; return; }
  el.innerHTML = sources.map(s => `<div class="li-title">${esc(s.name)} <span class="tag">${s.source_type}</span>${s.enabled?'<span class="tag" style="background:#dcfce7;color:#16a34a">启用</span>':'<span class="tag" style="background:#fef3c7;color:#b45309">禁用</span>'}</div>
    <div class="li-sub">${esc(s.url)} | 抓取${s.fetch_count}次 | 最后:${s.last_fetch_status}</div>
    <div class="li-ops"><button class="btn small" onclick="toggleSource('${esc(s.name)}',${!s.enabled})">${s.enabled?'禁用':'启用'}</button></div>`).join("");
}
function renderOpsExpiry(flags) {
  const el = document.getElementById("ops-expiry");
  if (!flags || !flags.length) { el.innerHTML = '<div class="li-sub">无过期内容</div>'; return; }
  el.innerHTML = flags.map(f => `<div class="li-title">${esc(f.flag_type)} <span class="tag" style="background:#fef3c7;color:#b45309">待审</span></div>
    <div class="li-body">${esc(f.reason)}</div>
    <div class="li-ops"><button class="btn small primary" onclick="reviewExpiry(${f.id},true)">标记已审</button></div>`).join("");
}
function renderOpsVersions(snaps) {
  const el = document.getElementById("ops-versions");
  if (!snaps || !snaps.length) { el.innerHTML = '<div class="li-sub">暂无快照</div>'; return; }
  el.innerHTML = snaps.map(s => `<div class="li-title">${esc(s.version_tag)}</div>
    <div class="li-sub">卡片${s.card_count} | 采集${s.capture_count} | ${esc(s.description)}</div>
    <div class="li-ops"><button class="btn small" onclick="rollbackVersion('${esc(s.version_tag)}')">回滚到此版本</button></div>`).join("");
}
function renderOpsChanges(logs) {
  const el = document.getElementById("ops-changes");
  if (!logs || !logs.length) { el.innerHTML = '<div class="li-sub">暂无变更记录</div>'; return; }
  el.innerHTML = logs.slice(0,20).map(c => `<div class="li-title">${esc(c.action)} <span class="tag">${esc(c.entity_type)}</span></div>
    <div class="li-sub">${esc(c.reason)}</div>`).join("");
}
document.getElementById("ops-run-btn").onclick = async () => {
  const r = await API("/api/ops/run", { method: "POST" });
  document.getElementById("ops-msg").textContent = r.message;
  setTimeout(loadOps, 3000);
};
document.getElementById("ops-quick-btn").onclick = async () => {
  const r = await API("/api/ops/run-quick", { method: "POST" });
  document.getElementById("ops-msg").textContent = r.message;
  setTimeout(loadOps, 2000);
};
document.getElementById("ops-refresh-btn").onclick = loadOps;
document.getElementById("ops-src-add").onclick = async () => {
  const name = document.getElementById("ops-src-name").value.trim();
  const url = document.getElementById("ops-src-url").value.trim();
  const type = document.getElementById("ops-src-type").value;
  if (!name || !url) { document.getElementById("ops-msg").textContent = "请填写名称和URL"; return; }
  await API("/api/ops/sources/add", { method: "POST", body: { name, url, source_type: type } });
  document.getElementById("ops-src-name").value = "";
  document.getElementById("ops-src-url").value = "";
  document.getElementById("ops-msg").textContent = "已添加";
  loadOps();
};
function toggleSource(name, enabled) {
  API("/api/ops/sources/toggle", { method: "POST", body: { name, enabled } }).then(loadOps);
}
function reviewExpiry(flagId, reviewed) {
  API("/api/ops/expiry/review", { method: "POST", body: { flag_id: flagId, reviewed, result: "已审查" } }).then(loadOps);
}
function rollbackVersion(tag) {
  if (!confirm("确认回滚到版本 " + tag + "？当前数据将被替换。")) return;
  API("/api/ops/rollback", { method: "POST", body: { version_tag: tag } }).then(r => {
    document.getElementById("ops-msg").textContent = r.rolled_back ? "回滚成功" : "回滚失败";
    loadOps();
  });
}

/* ==================== 终极形态：RAG 问答 ==================== */
async function askQ() {
  const input = document.getElementById("ask-input");
  const q = input.value.trim();
  if (!q) return;
  const log = document.getElementById("chat-log");
  log.innerHTML += `<div class="msg-row msg-user">${esc(q)}</div>`;
  input.value = "";
  log.innerHTML += `<div class="msg-row msg-ai">正在检索知识库...</div>`;
  const last = log.lastElementChild;
  try {
    const r = await API("/api/rag/ask", { method: "POST", body: { question: q } });
    let html = esc(r.answer).replace(/\n/g, "<br>");
    if (r.sources && r.sources.length) {
      html += `<div class="sources-list"><span class="hint">引用来源：</span>`;
      html += r.sources.map(s => `<span class="tag" title="${esc(s.library)}">${esc(s.title)}</span>`).join(" ");
      html += `</div>`;
    }
    last.innerHTML = html;
    document.getElementById("ask-mode").textContent = r.mode === "ai" ? "AI 模式 · RAG 深度检索" : "规则检索模式（配置 AI 后更智能）";
  } catch (e) { last.textContent = "出错：" + e.message; }
  log.scrollTop = log.scrollHeight;
}

// RAG 按钮绑定
if (document.getElementById("ask-rag-btn")) {
  document.getElementById("ask-rag-btn").onclick = () => askQ();
}
if (document.getElementById("ask-btn")) {
  document.getElementById("ask-btn").onclick = () => askQ();
}

/* ==================== 终极形态：知识图谱 ==================== */
async function loadGraph() {
  try {
    const data = await API("/api/kg/graph");
    document.getElementById("kg-entities").textContent = data.stats?.entities || 0;
    document.getElementById("kg-relations").textContent = data.stats?.relations || 0;
    renderKgGraph(data);
  } catch (e) { console.error("KG load error:", e); }
}

function renderKgGraph(data) {
  const svg = document.getElementById("kg-svg");
  if (!svg) return;
  const W = svg.clientWidth || 800, H = svg.clientHeight || 500;
  svg.innerHTML = "";
  if (!data.nodes || !data.nodes.length) {
    svg.innerHTML = `<text x="${W/2}" y="${H/2}" text-anchor="middle" fill="#999" font-size="14">暂无图谱数据，点击「扫描全部卡片」生成</text>`;
    return;
  }
  // 简单力导向布局
  const nodes = data.nodes.map((n, i) => ({
    ...n,
    x: W/2 + (Math.cos(i * 2.399) * 150),
    y: H/2 + (Math.sin(i * 2.399) * 150),
    vx: 0, vy: 0,
  }));
  const nodeMap = {};
  nodes.forEach(n => nodeMap[n.id] = n);
  const links = data.links.filter(l => nodeMap[l.source] && nodeMap[l.target]);

  // 迭代力导向
  for (let iter = 0; iter < 100; iter++) {
    // 斥力
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x, dy = nodes[j].y - nodes[i].y;
        const dist = Math.max(Math.sqrt(dx*dx + dy*dy), 1);
        const force = 800 / (dist * dist);
        const fx = (dx/dist) * force, fy = (dy/dist) * force;
        nodes[i].vx -= fx; nodes[i].vy -= fy;
        nodes[j].vx += fx; nodes[j].vy += fy;
      }
    }
    // 引力（连线）
    for (const l of links) {
      const s = nodeMap[l.source], t = nodeMap[l.target];
      const dx = t.x - s.x, dy = t.y - s.y;
      const dist = Math.max(Math.sqrt(dx*dx + dy*dy), 1);
      const force = (dist - 100) * 0.05;
      const fx = (dx/dist) * force, fy = (dy/dist) * force;
      s.vx += fx; s.vy += fy; t.vx -= fx; t.vy -= fy;
    }
    // 中心引力
    for (const n of nodes) {
      n.vx += (W/2 - n.x) * 0.01;
      n.vy += (H/2 - n.y) * 0.01;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(40, Math.min(W-40, n.x));
      n.y = Math.max(40, Math.min(H-40, n.y));
    }
  }

  // 绘制连线
  for (const l of links) {
    const s = nodeMap[l.source], t = nodeMap[l.target];
    svg.innerHTML += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#ddd" stroke-width="${Math.min(l.weight || 1, 3)}" opacity="0.6"/>`;
    const mx = (s.x+t.x)/2, my = (s.y+t.y)/2;
    svg.innerHTML += `<text x="${mx}" y="${my}" text-anchor="middle" font-size="10" fill="#aaa">${esc(l.label || "")}</text>`;
  }
  // 绘制节点
  const colors = { concept: "#7F77DD", person: "#D85A30", tool: "#5DCAA5", method: "#EF9F27", field: "#378ADD" };
  for (const n of nodes) {
    const r = Math.max(8, Math.min(24, 8 + (n.freq || 1) * 2));
    const color = colors[n.type] || colors.concept;
    svg.innerHTML += `<circle cx="${n.x}" cy="${n.y}" r="${r}" fill="${color}" opacity="0.8" stroke="#fff" stroke-width="2"><title>${esc(n.name)} (${n.type}) · 出现${n.freq}次</title></circle>`;
    svg.innerHTML += `<text x="${n.x}" y="${n.y + r + 14}" text-anchor="middle" font-size="11" fill="#333">${esc(n.name)}</text>`;
  }
}

// 知识图谱按钮
if (document.getElementById("kg-refresh")) {
  document.getElementById("kg-refresh").onclick = loadGraph;
}
if (document.getElementById("kg-ingest-all")) {
  document.getElementById("kg-ingest-all").onclick = async () => {
    const btn = document.getElementById("kg-ingest-all");
    btn.textContent = "扫描中...";
    try {
      // 获取所有卡片并逐个抽取
      const { cards } = await API("/api/cards");
      for (const c of (cards || []).slice(0, 30)) {
        await API("/api/kg/ingest", { method: "POST", body: { card_id: c.id, title: c.title, content: c.content, tags: c.tags } });
      }
      btn.textContent = "✅ 扫描完成";
      loadGraph();
    } catch (e) { btn.textContent = "❌ 失败"; console.error(e); }
    setTimeout(() => btn.textContent = "📊 扫描全部卡片", 2000);
  };
}

/* ==================== 终极形态：学习看板 ==================== */
async function loadLearn() {
  try {
    const data = await API("/api/learning/dashboard");
    document.getElementById("lr-streak").textContent = data.streak?.current_streak || 0;
    document.getElementById("lr-longest").textContent = data.streak?.longest_streak || 0;
    document.getElementById("lr-cards").textContent = data.cards_count || 0;
    document.getElementById("lr-review").textContent = data.reviews_today || 0;

    // 盲区
    document.getElementById("lr-gaps").innerHTML = data.gaps?.length
      ? data.gaps.map(g => `<div class="list-item"><div class="li-title">⚠ ${esc(g.topic)} <span class="tag">${esc(g.type)}</span></div><div class="li-sub">${esc(g.detail)}</div></div>`).join("")
      : '<div class="list-item"><div class="li-sub">知识覆盖良好，没有明显盲区！</div></div>';

    // 学习路径
    document.getElementById("lr-paths").innerHTML = data.paths?.length
      ? data.paths.map(p => `<div class="list-item"><div class="li-title">📍 ${esc(p.title)}</div><div class="li-sub">${(p.steps||[]).map(s => `Step ${s.step}: ${esc(s.title)}`).join(" → ")}</div></div>`).join("")
      : '<div class="list-item"><div class="li-sub">暂无学习路径，点击上方按钮生成。</div></div>';

    // 覆盖度
    const cov = data.coverage || {};
    const maxCov = Math.max(...Object.values(cov), 1);
    document.getElementById("lr-coverage").innerHTML = Object.entries(cov).map(([k, v]) =>
      `<div style="margin:4px 0"><span style="display:inline-block;width:100px;font-size:12px">${esc(k)}</span><div style="display:inline-block;height:16px;background:#7F77DD;border-radius:4px;width:${(v/maxCov*200).toFixed(0)}px;vertical-align:middle"></div> <span style="font-size:12px;color:#888">${v}条</span></div>`
    ).join("") || '<p class="hint">暂无数据</p>';
  } catch (e) { console.error("Learn load error:", e); }
}

// 学习路径按钮
if (document.getElementById("lr-gen-path")) {
  document.getElementById("lr-gen-path").onclick = async () => {
    const topic = document.getElementById("lr-topic").value.trim();
    const btn = document.getElementById("lr-gen-path");
    btn.textContent = "生成中...";
    try {
      await API("/api/learning/path", { method: "POST", body: { topic } });
      btn.textContent = "✅ 已生成";
      loadLearn();
    } catch (e) { btn.textContent = "❌ 失败"; }
    setTimeout(() => btn.textContent = "生成学习路径", 2000);
  };
}

/* ==================== 终极形态：Agent 中心 ==================== */
async function loadAgents() {
  try {
    const data = await API("/api/agent/log");
    document.getElementById("agent-log").innerHTML = data?.length
      ? data.map(l => {
          const time = l.created_at ? new Date(l.created_at * 1000).toLocaleString() : "";
          return `<div class="list-item"><div class="li-title">[${esc(l.agent_name)}] ${esc(l.action)} <span class="tag">${time}</span></div><div class="li-sub">${esc((l.detail||"").slice(0, 100))}</div></div>`;
        }).join("")
      : '<div class="list-item"><div class="li-sub">Agent 还没有活动记录。点击上方按钮指挥它们！</div></div>';
  } catch (e) { console.error("Agent log error:", e); }
}

async function runAgent(type) {
  const resultBox = document.getElementById("agent-result");
  resultBox.classList.remove("hidden");
  resultBox.textContent = "Agent 团队正在协作工作中...";
  try {
    const r = await API("/api/agent/run", { method: "POST", body: { type, input: "" } });
    let html = `<h4>任务: ${esc(r.task)}</h4>`;
    for (const [agent, result] of Object.entries(r.agents || {})) {
      html += `<div style="margin:8px 0"><b>[${esc(agent)}]</b><br>`;
      if (result.digest) html += esc(result.digest).replace(/\n/g, "<br>").slice(0, 500);
      else if (result.answer) html += esc(result.answer).replace(/\n/g, "<br>").slice(0, 300);
      else if (result.path) html += esc(JSON.stringify(result.path)).slice(0, 300);
      else html += esc(JSON.stringify(result)).slice(0, 300);
      html += `</div>`;
    }
    resultBox.innerHTML = html;
    loadAgents();
  } catch (e) { resultBox.textContent = "出错: " + e.message; }
}

initAuth();
