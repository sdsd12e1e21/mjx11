(function () {
  "use strict";

  var ACTIVE_SPACE_KEY = "studyrelay_active_space_id";
  var NOTES_MAX_LENGTH = 500;

  var state = {
    spaces: [],
    activeSpaceId: null,
    cards: [],
    plan: null,
    currentCardIndex: 0,
    currentAssessment: null,
    pcAvailable: false,
    saving: false,
    generation: 0,
  };

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function show(el) { el && el.classList.remove("hidden"); }
  function hide(el) { el && el.classList.add("hidden"); }

  function generateRequestId() {
    return "req-" + Date.now().toString(36) + "-" + Math.random().toString(36).substring(2, 10);
  }

  async function api(path, opts) {
    opts = opts || {};
    var gen = state.generation;
    var controller = null;
    if (typeof AbortController !== "undefined") {
      controller = new AbortController();
    }

    var fetchPromise = fetch(path, {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: controller ? controller.signal : undefined,
    });

    if (controller) {
      state._currentController = controller;
    }

    var resp;
    try {
      resp = await fetchPromise;
    } catch (e) {
      if (e.name === "AbortError") {
        throw new Error("Request cancelled (space switched)");
      }
      throw e;
    }

    if (state.generation !== gen) {
      throw new Error("Stale response discarded (space switched)");
    }

    if (!resp.ok) {
      var text = await resp.text();
      throw new Error("API " + path + " failed: " + resp.status + " " + text);
    }
    return resp.json();
  }

  function cancelPendingRequests() {
    if (state._currentController) {
      try { state._currentController.abort(); } catch (e) { /* ignore */ }
      state._currentController = null;
    }
  }

  async function checkHealth() {
    try {
      var data = await api("/health");
      state.pcAvailable = data.powercontext && data.powercontext.available;
      var badge = $("#health-badge");
      if (state.pcAvailable) {
        badge.textContent = "PowerContext 已连接";
        badge.className = "health-badge health-ok";
      } else {
        badge.textContent = "PowerContext 不可用";
        badge.className = "health-badge health-degraded";
      }
    } catch (e) {
      state.pcAvailable = false;
      var badge = $("#health-badge");
      badge.textContent = "PowerContext 不可用";
      badge.className = "health-badge health-degraded";
    }
  }

  async function loadSpaces() {
    try {
      var data = await api("/api/spaces");
      state.spaces = data.spaces || [];
      renderSpaces();
    } catch (e) {
      if (e.message.indexOf("cancelled") === -1 && e.message.indexOf("Stale") === -1) {
        showError("加载学习空间失败: " + e.message);
      }
    }
  }

  function renderSpaces() {
    var container = $("#space-list");
    container.innerHTML = "";
    state.spaces.forEach(function (space) {
      var card = document.createElement("div");
      card.className = "space-card" + (state.activeSpaceId === space.space_id ? " active" : "");
      card.dataset.spaceId = space.space_id;

      var left = document.createElement("div");
      var nameEl = document.createElement("span");
      nameEl.className = "space-name";
      nameEl.textContent = space.name;
      left.appendChild(nameEl);

      if (space.is_synthetic) {
        var badgeEl = document.createElement("span");
        badgeEl.className = "space-synthetic-badge";
        badgeEl.textContent = "合成演示";
        left.appendChild(badgeEl);
      }

      if (space.scope_id) {
        var scopeEl = document.createElement("div");
        scopeEl.className = "space-scope";
        scopeEl.textContent = "scope: " + space.scope_id.substring(0, 16) + "...";
        left.appendChild(scopeEl);
      }

      card.appendChild(left);
      card.addEventListener("click", function () { selectSpace(space.space_id); });
      container.appendChild(card);
    });
  }

  async function selectSpace(spaceId) {
    cancelPendingRequests();
    state.generation++;
    state.activeSpaceId = spaceId;
    state.saving = false;
    state.currentAssessment = null;
    try { localStorage.setItem(ACTIVE_SPACE_KEY, spaceId); } catch (e) { /* ignore */ }
    renderSpaces();
    hide($("#review-section"));
    var saveBtn = $("#save-session-btn");
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = "保存本次学习";
    }
    await loadPreferences();
    await loadPlan();
    show($("#setup-section"));
    show($("#plan-section"));
    show($("#memory-panel"));
    loadRecords();
  }

  async function loadPreferences() {
    if (!state.activeSpaceId) return;
    try {
      var data = await api("/api/spaces/" + state.activeSpaceId + "/preferences");
      if (data.preferences) {
        $("#daily-minutes").value = data.preferences.daily_minutes;
        $("#learning-goal").value = data.preferences.learning_goal;
        hide($("#setup-form"));
        show($("#current-prefs"));
        $("#prefs-minutes").textContent = data.preferences.daily_minutes;
        $("#prefs-goal").textContent = data.preferences.learning_goal;
      } else {
        show($("#setup-form"));
        hide($("#current-prefs"));
      }
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) return;
      if (!state.pcAvailable) {
        show($("#setup-form"));
        hide($("#current-prefs"));
      }
    }
  }

  async function savePreferences() {
    if (!state.activeSpaceId || !state.pcAvailable) return;
    var dailyMinutes = parseInt($("#daily-minutes").value, 10);
    var goal = $("#learning-goal").value.trim();
    if (dailyMinutes < 5 || dailyMinutes > 120) {
      showStatus("#setup-status", "分钟数需在 5-120 之间", true);
      return;
    }
    if (!goal) {
      showStatus("#setup-status", "请输入学习目标", true);
      return;
    }
    try {
      var data = await api("/api/spaces/" + state.activeSpaceId + "/preferences", {
        method: "PUT",
        body: { daily_minutes: dailyMinutes, learning_goal: goal },
      });
      var citationInfo = "";
      if (data.memory_citations && data.memory_citations[0]) {
        citationInfo = ", artifact: " + data.memory_citations[0].artifact_id.substring(0, 12) + "...";
      }
      showStatus("#setup-status", "已保存到 PowerContext（" + data.elapsed_ms + "ms" + citationInfo + "）", false);
      hide($("#setup-form"));
      show($("#current-prefs"));
      $("#prefs-minutes").textContent = dailyMinutes;
      $("#prefs-goal").textContent = goal;
      await loadPlan();
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) return;
      showStatus("#setup-status", "保存失败: " + e.message, true);
    }
  }

  async function loadPlan() {
    if (!state.activeSpaceId) return;
    try {
      var data = await api("/api/spaces/" + state.activeSpaceId + "/plan");
      state.plan = data.plan;
      renderPlan(data);
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) return;
      if (!state.pcAvailable) {
        $("#plan-summary").textContent = "PowerContext 不可用，无法生成复习计划";
      }
    }
  }

  function renderPlan(data) {
    var plan = data.plan;
    if (!plan || !plan.items || plan.items.length === 0) {
      hide($("#plan-items"));
      show($("#plan-empty"));
      $("#plan-summary").textContent = "";
      $("#plan-continuation").textContent = data.continuation_reason || "";
      return;
    }
    hide($("#plan-empty"));
    show($("#plan-items"));

    var summaryText = plan.items.length + " 张卡片，预计 " + plan.total_estimated_minutes + " 分钟";
    if (data.budget_note) {
      summaryText += "（" + data.budget_note + "）";
    }
    $("#plan-summary").textContent = summaryText;
    $("#plan-continuation").textContent = data.continuation_reason || "";

    var refsHtml = renderMemoryRefs(data.plan.memory_references || [], data.scope_id);
    $("#plan-memory-refs").innerHTML = refsHtml;

    var container = $("#plan-items");
    container.innerHTML = "";
    plan.items.forEach(function (item, idx) {
      var row = document.createElement("div");
      row.className = "plan-item";
      row.addEventListener("click", function () { startReview(idx); });

      var info = document.createElement("div");
      info.className = "plan-item-info";
      var topic = document.createElement("div");
      topic.className = "plan-item-topic";
      topic.textContent = item.card.topic;
      info.appendChild(topic);
      var reason = document.createElement("div");
      reason.className = "plan-item-reason";
      reason.textContent = item.reason;
      info.appendChild(reason);

      var badgeEl = document.createElement("span");
      badgeEl.className = "plan-item-priority priority-" + item.priority;
      var labels = { "new": "新卡片", "needs_work": "需加强", "mastered_due": "到期复习" };
      badgeEl.textContent = labels[item.priority] || item.priority;

      row.appendChild(info);
      row.appendChild(badgeEl);
      container.appendChild(row);
    });
  }

  function renderMemoryRefs(refs, scopeId) {
    if (!refs || refs.length === 0) return "";
    var html = "<details><summary>记忆引用 (" + refs.length + " 条)</summary>";
    refs.forEach(function (ref) {
      html += '<div class="memory-ref-item">' +
        "artifact: " + escapeHtml(ref.artifact_id || "?") +
        " rev:" + escapeHtml(String(ref.revision || "?")) +
        " state:" + escapeHtml(ref.state || "?") +
        " scope:" + escapeHtml(scopeId || "?") +
        "</div>";
    });
    html += "</details>";
    return html;
  }

  async function loadCards() {
    try {
      var data = await api("/api/cards");
      state.cards = data.cards || [];
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) return;
      showError("加载卡片失败: " + e.message);
    }
  }

  function findCard(cardId) {
    for (var i = 0; i < state.cards.length; i++) {
      if (state.cards[i].id === cardId) return state.cards[i];
    }
    return null;
  }

  function startReview(index) {
    if (!state.plan || !state.plan.items || index >= state.plan.items.length) return;
    state.currentCardIndex = index;
    state.currentAssessment = null;
    show($("#review-section"));
    renderCurrentCard();
    $("#review-section").scrollIntoView({ behavior: "smooth" });
  }

  function renderCurrentCard() {
    var item = state.plan.items[state.currentCardIndex];
    var card = findCard(item.card.id);
    if (!card) return;

    $("#review-topic").textContent = card.topic;
    $("#review-question").textContent = card.question;
    $("#review-answer").textContent = card.answer;
    hide($("#review-answer"));
    show($("#show-answer-btn"));
    hide($("#assessment-row"));
    hide($("#notes-row"));
    show($("#save-session-btn"));
    $("#save-session-btn").disabled = false;
    hide($("#review-nav"));
    $("#session-status").textContent = "";
    $("#review-notes").value = "";
    $("#review-notes").maxLength = NOTES_MAX_LENGTH;

    var total = state.plan.items.length;
    $("#review-progress").textContent = (state.currentCardIndex + 1) + " / " + total;
  }

  function showAnswer() {
    show($("#review-answer"));
    hide($("#show-answer-btn"));
    show($("#assessment-row"));
    show($("#notes-row"));
  }

  function selectAssessment(assessment) {
    state.currentAssessment = assessment;
    $$(".assessment-row .btn").forEach(function (btn) {
      btn.style.outline = btn.dataset.assessment === assessment ? "3px solid #333" : "none";
    });
    show($("#save-session-btn"));
  }

  async function saveSession() {
    if (!state.activeSpaceId || !state.currentAssessment || state.saving) return;
    var item = state.plan.items[state.currentCardIndex];
    var notes = $("#review-notes").value.trim();
    if (notes.length > NOTES_MAX_LENGTH) {
      notes = notes.substring(0, NOTES_MAX_LENGTH);
    }

    state.saving = true;
    var saveBtn = $("#save-session-btn");
    saveBtn.disabled = true;
    saveBtn.textContent = "保存中...";

    var requestId = generateRequestId();

    try {
      var data = await api("/api/spaces/" + state.activeSpaceId + "/session", {
        method: "POST",
        body: {
          card_id: item.card.id,
          assessment: state.currentAssessment,
          notes: notes || null,
          request_id: requestId,
        },
      });

      if (data.duplicate) {
        showStatus("#session-status", "重复请求已忽略", false);
        saveBtn.disabled = false;
        saveBtn.textContent = "保存本次学习";
        state.saving = false;
        return;
      }

      var citation = data.memory_citation || {};
      showStatus("#session-status",
        "已保存（" + data.elapsed_ms + "ms） artifact: " +
        (citation.artifact_id || "?").substring(0, 12) + "... rev:" + (citation.revision || "?") +
        " scope: " + (citation.scope_id || "?").substring(0, 12) + "...",
        false
      );
      hide($("#save-session-btn"));
      show($("#review-nav"));
      state.saving = false;
      await loadPlan();
      await loadRecords();
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) {
        state.saving = false;
        return;
      }
      showStatus("#session-status", "保存失败: " + e.message, true);
      saveBtn.disabled = false;
      saveBtn.textContent = "保存本次学习";
      state.saving = false;
    }
  }

  function nextCard() {
    if (state.currentCardIndex < state.plan.items.length - 1) {
      state.currentCardIndex++;
      state.currentAssessment = null;
      renderCurrentCard();
    } else {
      hide($("#review-section"));
    }
  }

  async function loadRecords() {
    if (!state.activeSpaceId || !state.pcAvailable) return;
    try {
      var data = await api("/api/spaces/" + state.activeSpaceId + "/records");
      renderRecords(data.records || [], data.scope_id);
    } catch (e) {
      /* ignore stale/cancelled */
    }
  }

  function renderRecords(records, scopeId) {
    var container = $("#memory-records");
    if (!records || records.length === 0) {
      container.innerHTML = '<div class="hint">暂无学习记录</div>';
      return;
    }
    container.innerHTML = "";
    records.slice().reverse().forEach(function (rec) {
      var card = findCard(rec.card_id);
      var item = document.createElement("div");
      item.className = "memory-record-item";
      var dateStr = rec.date || "?";
      var assessmentLabel = rec.assessment === "needs_work" ? "需加强" : rec.assessment === "mastered" ? "已掌握" : rec.assessment || "?";

      var titleDiv = document.createElement("div");
      var strongEl = document.createElement("strong");
      strongEl.textContent = dateStr;
      titleDiv.appendChild(strongEl);
      titleDiv.appendChild(document.createTextNode(" - " + (card ? card.topic : rec.card_id) + " [" + assessmentLabel + "]"));

      var metaDiv = document.createElement("div");
      metaDiv.className = "record-meta";
      metaDiv.textContent = "artifact: " + (rec._artifact_id || "?") +
        " rev:" + (rec._revision || "?") +
        " scope: " + (rec._scope_id || scopeId || "?");

      item.appendChild(titleDiv);
      item.appendChild(metaDiv);
      container.appendChild(item);
    });
  }

  async function exportData(format) {
    if (!state.activeSpaceId) return;
    try {
      var resp = await fetch("/api/spaces/" + state.activeSpaceId + "/export?format=" + format);
      if (!resp.ok) throw new Error("Export failed: " + resp.status);
      if (format === "json") {
        var data = await resp.json();
        var blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        downloadBlob(blob, "studyrelay-export.json");
      } else {
        var text = await resp.text();
        var mdBlob = new Blob([text], { type: "text/markdown" });
        downloadBlob(mdBlob, "studyrelay-export.md");
      }
    } catch (e) {
      showError("导出失败: " + e.message);
    }
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function addSpace() {
    var input = $("#new-space-name");
    var name = input.value.trim();
    if (!name) return;
    try {
      var data = await api("/api/spaces", { method: "POST", body: { name: name } });
      input.value = "";
      await loadSpaces();
      selectSpace(data.space_id);
    } catch (e) {
      if (e.message.indexOf("cancelled") !== -1 || e.message.indexOf("Stale") !== -1) return;
      showError("添加空间失败: " + e.message);
    }
  }

  function showStatus(sel, msg, isError) {
    var el = $(sel);
    el.textContent = msg;
    el.className = "status-line " + (isError ? "status-error" : "status-success");
  }

  function showError(msg) {
    $("#error-message").textContent = msg;
    show($("#error-overlay"));
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function bindEvents() {
    $("#save-prefs-btn").addEventListener("click", savePreferences);
    $("#edit-prefs-btn").addEventListener("click", function () {
      show($("#setup-form"));
      hide($("#current-prefs"));
    });
    $("#show-answer-btn").addEventListener("click", showAnswer);
    $("#save-session-btn").addEventListener("click", saveSession);
    $("#next-card-btn").addEventListener("click", nextCard);
    $("#add-space-btn").addEventListener("click", addSpace);
    $("#new-space-name").addEventListener("keydown", function (e) {
      if (e.key === "Enter") addSpace();
    });
    $("#export-json-btn").addEventListener("click", function () { exportData("json"); });
    $("#export-md-btn").addEventListener("click", function () { exportData("markdown"); });
    $("#error-retry-btn").addEventListener("click", function () {
      hide($("#error-overlay"));
      init();
    });

    $$(".assessment-row .btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        selectAssessment(btn.dataset.assessment);
      });
    });
  }

  async function init() {
    bindEvents();
    await checkHealth();
    await loadCards();
    await loadSpaces();

    var savedSpaceId = null;
    try { savedSpaceId = localStorage.getItem(ACTIVE_SPACE_KEY); } catch (e) { /* ignore */ }
    if (savedSpaceId && state.spaces.some(function (s) { return s.space_id === savedSpaceId; })) {
      selectSpace(savedSpaceId);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
