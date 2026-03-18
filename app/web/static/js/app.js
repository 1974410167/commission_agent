(function () {
  // 前端状态刻意保持很小：
  // 只维护当前会话、消息列表、上轮响应和 loading 状态，
  // 避免为了 demo 页面引入复杂前端框架。
  const payload = JSON.parse(document.getElementById("pageData").textContent);
  const state = {
    conversationId: payload.defaultConversationId,
    messages: [],
    lastResponse: null,
    sampleConversations: payload.sampleConversations || [],
    loading: false,
  };

  const el = {
    conversationId: document.getElementById("conversationId"),
    userRole: document.getElementById("userRole"),
    boundCreatorId: document.getElementById("boundCreatorId"),
    quickQuestions: document.getElementById("quickQuestions"),
    messageList: document.getElementById("messageList"),
    messageInput: document.getElementById("messageInput"),
    sendBtn: document.getElementById("sendBtn"),
    newConversationBtn: document.getElementById("newConversationBtn"),
    resetConversationBtn: document.getElementById("resetConversationBtn"),
    errorBanner: document.getElementById("errorBanner"),
    loadingHint: document.getElementById("loadingHint"),
    modeBadge: document.getElementById("modeBadge"),
    debugMeta: document.getElementById("debugMeta"),
    normalizedFilters: document.getElementById("normalizedFilters"),
    missingSlots: document.getElementById("missingSlots"),
    evidenceList: document.getElementById("evidenceList"),
    chunkList: document.getElementById("chunkList"),
    workflowTraceList: document.getElementById("workflowTraceList"),
  };

  // conversation_id 在前端生成，方便现场演示时快速切新会话。
  function generateConversationId() {
    return `demo-${Date.now()}`;
  }

  function showError(message) {
    el.errorBanner.textContent = message;
    el.errorBanner.classList.remove("hidden");
  }

  function clearError() {
    el.errorBanner.textContent = "";
    el.errorBanner.classList.add("hidden");
  }

  function setLoading(loading) {
    state.loading = loading;
    el.sendBtn.disabled = loading;
    el.loadingHint.classList.toggle("hidden", !loading);
  }

  function updateModeBadge() {
    // 页面不再提供 LLM 开关，运行模式完全以服务端真实状态为准。
    let label = "LLM + RAG";
    if (state.lastResponse?.debug?.nlu_mode === "llm_based") label = "LLM + RAG";
    if (state.lastResponse?.debug?.nlu_mode === "llm_unavailable") label = "LLM Unavailable";
    el.modeBadge.textContent = label;
  }

  function renderQuickQuestions() {
    // 快捷问题来自 sample_conversations.json，
    // 但其中的占位符已经由后端替换成真实 ES 样例 id。
    el.quickQuestions.innerHTML = "";
    state.sampleConversations.forEach((item) => {
      const button = document.createElement("button");
      button.className = "quick-question";
      button.textContent = item.label;
      button.addEventListener("click", () => {
        if (item.role) {
          el.userRole.value = item.role;
        }
        if (item.bound_creator_id) {
          el.boundCreatorId.value = item.bound_creator_id;
        }
        el.messageInput.value = item.message;
      });
      el.quickQuestions.appendChild(button);
    });
  }

  function renderMessages() {
    el.messageList.innerHTML = "";
    state.messages.forEach((message) => {
      const wrapper = document.createElement("article");
      wrapper.className = `message ${message.role} ${message.action === "clarify" ? "clarify" : ""}`;

      const head = document.createElement("div");
      head.className = "message-head";
      head.innerHTML = `<span>${message.role === "user" ? "User" : "Agent"}</span><span>${message.intent || ""}</span>`;
      wrapper.appendChild(head);

      const answer = document.createElement("div");
      answer.className = "answer";
      renderAnswerContent(answer, message.content);
      wrapper.appendChild(answer);

      if (message.role === "assistant" && message.nextSuggestions?.length) {
        const section = document.createElement("div");
        section.className = "message-subsection";
        section.innerHTML = "<strong>Next suggestions</strong>";
        const list = document.createElement("div");
        list.className = "suggestion-list";
        message.nextSuggestions.forEach((suggestion) => {
          const pill = document.createElement("button");
          pill.className = "pill";
          pill.textContent = suggestion;
          pill.addEventListener("click", () => sendMessage(suggestion));
          list.appendChild(pill);
        });
        section.appendChild(list);
        wrapper.appendChild(section);
      }

      if (message.role === "assistant" && message.evidence?.length) {
        const section = document.createElement("div");
        section.className = "message-subsection";
        section.innerHTML = "<strong>Evidence</strong>";
        const compact = document.createElement("div");
        compact.className = "evidence-compact";
        message.evidence.slice(0, 4).forEach((item) => {
          const chip = document.createElement("div");
          chip.className = "evidence-chip";
          chip.textContent = `${item.type}: ${item.title}`;
          compact.appendChild(chip);
        });
        section.appendChild(compact);
        wrapper.appendChild(section);
      }

      el.messageList.appendChild(wrapper);
    });
    el.messageList.scrollTop = el.messageList.scrollHeight;
  }

  function renderAnswerContent(container, text) {
    container.innerHTML = "";
    const blocks = String(text || "").trim().split(/\n\s*\n/).filter(Boolean);
    if (!blocks.length) {
      container.textContent = text || "";
      return;
    }

    blocks.forEach((block) => {
      const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
      if (!lines.length) return;

      const unordered = lines.every((line) => line.startsWith("- "));
      const ordered = lines.every((line) => /^\d+\.\s/.test(line));

      if (unordered) {
        const ul = document.createElement("ul");
        lines.forEach((line) => {
          const li = document.createElement("li");
          li.innerHTML = inlineFormat(line.replace(/^- /, ""));
          ul.appendChild(li);
        });
        container.appendChild(ul);
        return;
      }

      if (ordered) {
        const ol = document.createElement("ol");
        lines.forEach((line) => {
          const li = document.createElement("li");
          li.innerHTML = inlineFormat(line.replace(/^\d+\.\s/, ""));
          ol.appendChild(li);
        });
        container.appendChild(ol);
        return;
      }

      const p = document.createElement("p");
      p.innerHTML = lines.map((line) => inlineFormat(line)).join("<br>");
      container.appendChild(p);
    });
  }

  function inlineFormat(text) {
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderDebug(response) {
    // 调试面板是整个 demo 的重点：
    // 它让面试官看到这不是一个“纯聊天壳”，而是真正走了
    // intent -> tool -> evidence -> retrieved_chunks 的链路。
    state.lastResponse = response;
    updateModeBadge();

    const debug = response.debug || {};
    const metaEntries = [
      ["action", response.action],
      ["intent", response.intent],
      ["nlu_mode", debug.nlu_mode || "-"],
      ["selected_tool", debug.selected_tool || "-"],
      ["conversation_id", state.conversationId],
      ["request_ms", debug.timing?.request_ms ?? "-"],
      ["workflow_ms", debug.timing?.workflow_ms ?? "-"],
    ];
    el.debugMeta.innerHTML = metaEntries.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
    el.normalizedFilters.textContent = JSON.stringify(response.normalized_filters || {}, null, 2);

    const missingSlots = response.missing_slots || [];
    if (!missingSlots.length) {
      el.missingSlots.innerHTML = '<span class="muted">无</span>';
    } else {
      el.missingSlots.innerHTML = missingSlots.map((item) => `<span class="tag">${item}</span>`).join("");
    }

    el.evidenceList.innerHTML = "";
    (response.evidence || []).forEach((item) => {
      const card = document.createElement("div");
      card.className = "debug-card";
      card.innerHTML = `
        <h4>${item.title}</h4>
        <p>${item.content_summary}</p>
        <div class="debug-meta">type=${item.type} | source=${item.source}${item.score != null ? ` | score=${item.score}` : ""}</div>
      `;
      el.evidenceList.appendChild(card);
    });

    el.chunkList.innerHTML = "";
    (debug.retrieved_chunks || []).forEach((item) => {
      const card = document.createElement("div");
      card.className = "debug-card";
      card.innerHTML = `
        <h4>${item.chunk_id}</h4>
        <p>${(item.heading_path || []).join(" / ")}</p>
        <div class="debug-meta">score=${item.score ?? "-"}</div>
      `;
      el.chunkList.appendChild(card);
    });

    el.workflowTraceList.innerHTML = "";
    (debug.workflow_trace || []).forEach((item) => {
      const card = document.createElement("div");
      card.className = "debug-card";
      card.innerHTML = `
        <h4>${item.node}</h4>
        <p>${item.summary || "-"}</p>
        <div class="debug-meta">status=${item.status || "-"} | duration_ms=${item.duration_ms ?? "-"}</div>
      `;
      el.workflowTraceList.appendChild(card);
    });
  }

  async function resetConversation(remoteReset) {
    // 既要清前端消息，也要按需清后端 memory。
    state.messages = [];
    state.lastResponse = null;
    renderMessages();
    renderDebug({
      action: "-",
      intent: "-",
      normalized_filters: {},
      evidence: [],
      missing_slots: [],
      debug: {},
    });
    clearError();
    if (remoteReset) {
      await fetch("/api/chat/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: state.conversationId }),
      });
    }
  }

  async function sendMessage(prefilledMessage) {
    const message = (prefilledMessage ?? el.messageInput.value).trim();
    if (!message || state.loading) return;
    clearError();

    state.conversationId = el.conversationId.value.trim() || generateConversationId();
    el.conversationId.value = state.conversationId;

    // 前端先做一层体验上的必填校验；
    // 真正的权限约束仍在后端 normalize / validate 节点兜底。
    if (el.userRole.value === "creator" && !el.boundCreatorId.value.trim()) {
      showError("creator 模式下必须填写 bound_creator_id。");
      return;
    }

    state.messages.push({ role: "user", content: message });
    renderMessages();
    el.messageInput.value = "";
    setLoading(true);

    try {
      const payload = {
        conversation_id: state.conversationId,
        message,
        user_role: el.userRole.value,
        bound_creator_id: el.boundCreatorId.value ? Number(el.boundCreatorId.value) : null,
      };
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const errorBody = await response.json();
          if (errorBody?.detail) {
            detail = errorBody.detail;
          }
        } catch (error) {
          // ignore parse failure and keep the generic HTTP error text
        }
        throw new Error(detail);
      }
      const data = await response.json();
      state.messages.push({
        role: "assistant",
        content: data.answer,
        action: data.action,
        intent: data.intent,
        nextSuggestions: data.next_suggestions,
        evidence: data.evidence,
      });
      renderMessages();
      renderDebug(data);
    } catch (error) {
      showError(`请求失败：${error.message}`);
    } finally {
      setLoading(false);
    }
  }

  el.sendBtn.addEventListener("click", () => sendMessage());
  el.messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  el.newConversationBtn.addEventListener("click", async () => {
    el.conversationId.value = generateConversationId();
    state.conversationId = el.conversationId.value;
    await resetConversation(false);
  });
  el.resetConversationBtn.addEventListener("click", async () => {
    await resetConversation(true);
  });
  el.userRole.addEventListener("change", () => {
    if (el.userRole.value === "operator") {
      el.boundCreatorId.value = "";
    }
  });

  renderQuickQuestions();
  updateModeBadge();
  renderDebug({
    action: "-",
    intent: "-",
    normalized_filters: {},
    evidence: [],
    missing_slots: [],
    debug: {},
  });
})();
