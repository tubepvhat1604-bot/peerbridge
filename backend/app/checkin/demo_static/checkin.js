/* PeerBridge – Check-in client.
 * - Nén ảnh trên trình duyệt (~1280px JPEG) trước khi gửi.
 * - id check-in tạo ở client (UUID) -> gửi lại khi lỗi mạng không bị trùng.
 * - Gửi xong hiện ảnh ngay với "Đang phân tích…", polling 2s/lần, tối đa 30s.
 * - Mọi nội dung từ server/AI hiển thị bằng textContent (không innerHTML) để tránh XSS.
 * Bản demo: lấy token của tài khoản demo từ /checkin-demo/token/{id} (chỉ bật khi APP_ENV=development).
 */
(() => {
  "use strict";
  const MAX_EDGE = 1280, QUALITY = 0.82, POLL_MS = 2000, POLL_MAX_MS = 30000;
  const $ = (id) => document.getElementById(id);
  const API = "/api/v1";
  const state = { token: null, feed: null, blob: null, previewUrl: null, pendingId: null, polling: new Set() };

  // ---------------------------------------------------------------- tiện ích
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) node.append(c instanceof Node ? c : String(c));
    return node;
  }
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() :
    "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));

  let toastTimer;
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
  }

  async function api(path, opts = {}) {
    const headers = new Headers(opts.headers || {});
    if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
    if (opts.json !== undefined) { headers.set("Content-Type", "application/json"); opts.body = JSON.stringify(opts.json); }
    const res = await fetch(path.startsWith("/checkin-demo") ? path : API + path, { credentials: "same-origin", ...opts, headers });
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const msg = data && (typeof data.detail === "string" ? data.detail : "Có lỗi xảy ra. Thử lại nhé.");
      const err = new Error(msg || `Lỗi ${res.status}`); err.status = res.status; throw err;
    }
    return data;
  }

  // ---------------------------------------------------------------- demo: đổi người dùng
  async function useUser(id) {
    state.token = (await api(`/checkin-demo/token/${id}`, { method: "POST" })).token;
    try { localStorage.setItem("pbDemoUser", id); } catch (_) {}
    await loadFeed();
  }

  async function setupDev() {
    const sel = $("devUser");
    const users = await api("/checkin-demo/users");
    sel.replaceChildren(...users.map((u) => el("option", { value: u.id }, u.name)));
    let saved = null;
    try { saved = localStorage.getItem("pbDemoUser"); } catch (_) {}
    if (saved && users.some((u) => String(u.id) === saved)) sel.value = saved;
    sel.addEventListener("change", () => useUser(sel.value));
    $("resetDemo").addEventListener("click", async () => {
      await api("/checkin-demo/reset", { method: "POST" }); toast("Đã làm lại dữ liệu demo"); loadFeed();
    });
    await useUser(sel.value);
  }

  // ---------------------------------------------------------------- render
  function renderTop(f) {
    $("pairNames").textContent = `${f.me.display_name} & ${f.partner.display_name}`;
    const s = $("streak");
    if (f.streak > 0) { s.textContent = `${f.streak} ngày liền`; s.hidden = false; s.title = "Số ngày liên tiếp cả hai cùng check-in"; }
    else s.hidden = true;
  }

  function photoOrText(c, cls) {
    if (c.image_url) return el("img", { class: cls, src: c.image_url, alt: `Ảnh check-in của ${c.owner_name}`, loading: "lazy" });
    return el("div", { class: cls === "photo" ? "photo-text" : "thumb-text" }, cls === "photo" ? (c.note || c.description || "Ghi chú học tập") : "Aa");
  }

  function renderHero(f) {
    const hero = $("hero"); hero.replaceChildren();
    const c = f.partner_latest;
    if (!c) {
      hero.append(el("div", { class: "empty" },
        el("strong", {}, `${f.partner.display_name} chưa có check-in nào`),
        "Check-in trước để bạn ấy thấy nhé."));
      return;
    }
    const mine = (emoji) => c.reactions.some((r) => r.user_id === f.me.user_id && r.emoji === emoji && !r.comment);
    const count = (emoji) => c.reactions.filter((r) => r.emoji === emoji && !r.comment).length;
    const comments = c.reactions.filter((r) => r.comment);

    const card = el("article", { class: "photo-card" },
      photoOrText(c, "photo"),
      el("div", { class: "card-body" },
      el("p", { class: "who" }, el("strong", {}, c.owner_name), el("time", { datetime: c.created_at }, c.relative)),
      el("p", { class: "caption" }, c.headline),
      c.concept_names.length ? el("ul", { class: "tags", "aria-label": "Nội dung" }, c.concept_names.map((n) => el("li", {}, n))) : null,
      c.bridge ? el("p", { class: "bridge-wrap" }, el("span", { class: "bridge" }, c.bridge)) : null,
      el("div", { class: "reacts", role: "group", "aria-label": "Thả cảm xúc" },
        (window.PB_EMOJIS || []).map((e) => el("button", {
          class: "react", type: "button", "aria-pressed": mine(e) ? "true" : "false", "aria-label": `Thả ${e}`,
          onclick: () => react(c.id, { emoji: e }),
        }, e, count(e) ? el("span", { class: "n" }, count(e)) : null))),
      comments.length ? el("ul", { class: "comments" }, comments.map((r) => el("li", {}, el("b", {}, r.display_name), `: ${r.comment}`))) : null,
      el("form", { class: "comment-form", onsubmit: (ev) => {
        ev.preventDefault(); const input = ev.target.elements.comment; const v = input.value.trim();
        if (v) react(c.id, { comment: v }).then(() => { input.value = ""; });
      } },
        el("input", { name: "comment", maxlength: "200", placeholder: `Nhắn ${c.owner_name}…`, "aria-label": "Bình luận" }),
        el("button", { class: "btn ghost", type: "submit" }, "Gửi"))),
    );
    hero.append(card);
  }

  function renderProgress(f) {
    const wrap = $("progress"); wrap.replaceChildren();
    for (const p of [f.me, f.partner]) {
      const pct = p.pacing === null || p.pacing === undefined ? (p.total_items ? p.done_items / p.total_items : 0) : Math.min(1, p.pacing);
      wrap.append(el("div", { class: "bar-row" },
        el("span", { class: "name" }, p.display_name, p.checked_in_today ? el("span", { class: "today-dot", title: "Đã check-in hôm nay", "aria-label": "đã check-in hôm nay" }) : null),
        el("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct * 100)), "aria-label": `Tiến độ của ${p.display_name}` },
          el("span", { style: `width:${Math.round(pct * 100)}%` })),
        el("span", { class: "meta" }, `${p.done_items}/${p.total_items} mục tuần này`)));
    }
  }

  function mineCard(c) {
    const card = el("article", { class: `mine-card state-${c.status}`, "data-id": c.id },
      photoOrText(c, "thumb"),
      el("div", {},
        el("h3", {}, c.headline),
        c.status === "done" && c.description && c.plan_item_label ? el("p", {}, c.description) : null,
        c.status === "not_study" ? el("p", {}, "Nếu đúng là bạn đang học, chọn mục bên dưới.") : null,
        c.status !== "processing" && c.status !== "done" && !c.options.length ? el("p", {}, "Chưa có mục nào trong plan tuần này.") : null,
        el("p", {}, c.relative),
        c.bridge ? el("p", {}, el("span", { class: "bridge" }, c.bridge)) : null),
    );
    if (["needs_confirm", "failed", "not_study"].includes(c.status)) {
      card.append(el("div", { class: "options", role: "group", "aria-label": "Chọn mục bạn vừa học" },
        c.options.map((o) => el("button", { class: "option", type: "button", onclick: () => confirmCheckin(c.id, o.plan_item_id) },
          o.label, o.concept_name ? el("small", {}, o.concept_name) : null)),
        el("button", { class: "option other", type: "button", onclick: () => confirmCheckin(c.id, null) }, "Mình học thứ khác")));
    }
    return card;
  }

  function renderMine(f) {
    const wrap = $("mine"); wrap.replaceChildren();
    const list = [];
    if (f.my_latest) list.push(f.my_latest);
    for (const p of f.my_pending) list.push(p);
    for (const c of list) {
      wrap.append(mineCard(c));
      if (c.status === "processing") startPolling(c.id);
    }
  }

  function renderHistory(f) {
    const wrap = $("historyWrap"), grid = $("history"); grid.replaceChildren();
    const items = f.history.filter((c) => !f.partner_latest || c.id !== f.partner_latest.id).slice(0, 8);
    wrap.hidden = items.length === 0;
    for (const c of items) {
      grid.append(el("li", { title: c.headline },
        c.image_url ? el("img", { src: c.image_url, alt: c.headline, loading: "lazy" }) : el("div", { class: "txt" }, c.note || c.description || ""),
        el("span", { class: "by" }, c.owner_name)));
    }
  }

  function renderDock(f) {
    const b = $("nudgeBtn");
    b.hidden = false;
    b.textContent = `Nhắc ${f.partner.display_name}`;
    b.disabled = !f.can_nudge;
    b.title = f.nudge_hint || `Gửi lời nhắc cho ${f.partner.display_name}`;
  }

  function render(f) { renderTop(f); renderHero(f); renderProgress(f); renderMine(f); renderHistory(f); renderDock(f); }

  async function loadFeed() {
    try { state.feed = await api("/pairs/me/feed"); render(state.feed); }
    catch (e) {
      $("pairNames").textContent = "Check-in";
      $("hero").replaceChildren(el("div", { class: "empty" }, el("strong", {}, "Chưa tải được trang"), e.message));
    }
  }

  // ---------------------------------------------------------------- polling
  function startPolling(id) {
    if (state.polling.has(id)) return;
    state.polling.add(id);
    const started = Date.now();
    const tick = async () => {
      try {
        const c = await api(`/checkins/${id}`);
        if (c.status !== "processing") {
          state.polling.delete(id); await loadFeed();
          if (c.status === "done") toast("Đã ghi nhận check-in");
          return;
        }
      } catch (_) { /* mạng chập chờn: thử tiếp */ }
      if (Date.now() - started > POLL_MAX_MS) {
        state.polling.delete(id);
        toast("AI phân tích hơi lâu. Kết quả sẽ hiện khi bạn mở lại trang.");
        return;
      }
      setTimeout(tick, POLL_MS);
    };
    setTimeout(tick, POLL_MS);
  }

  // ---------------------------------------------------------------- hành động
  async function confirmCheckin(id, planItemId) {
    try { await api(`/checkins/${id}/confirm`, { method: "POST", json: { plan_item_id: planItemId } }); toast("Đã ghi nhận check-in"); loadFeed(); }
    catch (e) { toast(e.message); }
  }
  async function react(id, body) {
    try { await api(`/checkins/${id}/reactions`, { method: "POST", json: body }); await loadFeed(); }
    catch (e) { toast(e.message); }
  }
  async function nudge() {
    if (!state.feed) return;
    try { const r = await api(`/pairs/${state.feed.pair_id}/nudge`, { method: "POST" }); toast(r.message); loadFeed(); }
    catch (e) { toast(e.message); }
  }

  // ---------------------------------------------------------------- ảnh: chọn, dán, kéo thả, nén
  async function decode(file) {
    if (window.createImageBitmap) {
      try { return await createImageBitmap(file, { imageOrientation: "from-image" }); } catch (_) {}
    }
    return new Promise((resolve, reject) => {
      const img = new Image(); const url = URL.createObjectURL(file);
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Không đọc được ảnh này. Hãy chọn ảnh JPG hoặc PNG.")); };
      img.src = url;
    });
  }
  async function compress(file) {
    const src = await decode(file);
    const w = src.width, h = src.height, scale = Math.min(1, MAX_EDGE / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
    if (src.close) src.close();
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", QUALITY));
    if (!blob) throw new Error("Không nén được ảnh. Thử chọn ảnh khác.");
    return blob;
  }
  async function takeFile(file) {
    if (!file || !file.type.startsWith("image/")) { showSheetError("Hãy chọn một tấm ảnh."); return; }
    showSheetError(null);
    try {
      state.blob = await compress(file);
      if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
      state.previewUrl = URL.createObjectURL(state.blob);
      const p = $("preview"); p.src = state.previewUrl; p.hidden = false; $("dropEmpty").hidden = true;
      $("sendBtn").disabled = false; $("pickBtn").textContent = "Chụp lại";
    } catch (e) { showSheetError(e.message); }
  }
  function showSheetError(msg) { const e = $("sheetError"); e.textContent = msg || ""; e.hidden = !msg; }

  function openSheet() {
    resetSheet(); const d = $("sheet");
    if (d.showModal) d.showModal(); else d.setAttribute("open", "");
  }
  function resetSheet() {
    state.blob = null; state.pendingId = null;
    $("preview").hidden = true; $("dropEmpty").hidden = false; $("note").value = "";
    $("sendBtn").disabled = true; $("sendBtn").textContent = "Gửi check-in"; $("pickBtn").textContent = "Chụp hoặc chọn ảnh";
    showSheetError(null);
  }
  function closeSheet() { const d = $("sheet"); if (d.close) d.close(); else d.removeAttribute("open"); }

  async function send({ textOnly = false } = {}) {
    const note = $("note").value.trim();
    if (textOnly && note.length < 3) { showSheetError("Viết vài chữ về việc bạn vừa học nhé."); $("note").focus(); return; }
    if (!textOnly && !state.blob) return;
    state.pendingId = state.pendingId || uuid(); // giữ id khi gửi lại => không bị trùng
    const btn = $("sendBtn"); btn.disabled = true; btn.textContent = "Đang gửi…"; showSheetError(null);
    try {
      let c;
      if (textOnly) c = await api("/checkins/text", { method: "POST", json: { id: state.pendingId, note } });
      else {
        const fd = new FormData();
        fd.append("id", state.pendingId); fd.append("image", state.blob, "checkin.jpg"); if (note) fd.append("note", note);
        c = await api("/checkins", { method: "POST", body: fd });
      }
      closeSheet(); toast("Đã gửi. AI đang xem ảnh của bạn…");
      await loadFeed(); startPolling(c.id);
    } catch (e) {
      btn.disabled = false; btn.textContent = "Gửi lại";
      showSheetError(e.status ? e.message : "Mất kết nối. Kiểm tra mạng rồi bấm Gửi lại.");
    }
  }

  function setupSheet() {
    $("checkinBtn").addEventListener("click", openSheet);
    $("nudgeBtn").addEventListener("click", nudge);
    $("pickBtn").addEventListener("click", () => $("fileInput").click());
    $("fileInput").addEventListener("change", (e) => { takeFile(e.target.files[0]); e.target.value = ""; });
    $("sendBtn").addEventListener("click", () => send());
    $("textOnlyBtn").addEventListener("click", () => send({ textOnly: true }));
    $("sheet").addEventListener("close", resetSheet);
    document.addEventListener("paste", (e) => {
      const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
      if (!item) return;
      e.preventDefault();
      if (!$("sheet").open) openSheet();
      takeFile(item.getAsFile());
    });
    const drop = $("drop");
    drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("dragging"); });
    drop.addEventListener("dragleave", () => drop.classList.remove("dragging"));
    drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("dragging"); takeFile(e.dataTransfer.files[0]); });
  }

  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadFeed(); });
  setInterval(() => { if (!document.hidden && !$("sheet").open) loadFeed(); }, 60000);

  setupSheet(); setupDev().catch((e) => toast(e.message));
})();
