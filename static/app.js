/* 个人AI知识库 - 前端逻辑 */
const API = (path, opts = {}) => fetch(path, {
  headers: { "Content-Type": "application/json", "Authorization": "Bearer " + localStorage.getItem("token") },
  body: opts.body ? JSON.stringify(opts.body) : undefined,
  ...opts,
}).then(async r => {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || "请求失败");
  return data;
});
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
  const loaders = { dashboard: loadDashboard, capture: loadCaptures, library: loadLibrary, ask: loadAsk, review: loadReviews, meta: loadMeta, profile: loadProfile, settings: loadSettings };
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
document.getElementById("ask-btn").onclick = askQ;
async function askQ() {
  const input = document.getElementById("ask-input");
  const q = input.value.trim();
  if (!q) return;
  const log = document.getElementById("chat-log");
  log.innerHTML += `<div class="msg-row msg-user">${esc(q)}</div>`;
  input.value = "";
  log.innerHTML += `<div class="msg-row msg-ai">思考中…</div>`;
  const last = log.lastElementChild;
  try {
    const r = await API("/api/ask", { method: "POST", body: { question: q } });
    last.innerHTML = esc(r.answer);
  } catch (e) { last.textContent = "出错：" + e.message; }
  log.scrollTop = log.scrollHeight;
}

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

initAuth();
