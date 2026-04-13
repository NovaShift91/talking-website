/**
 * NovaShift Talking Website Widget
 * Drop this script tag on any site:
 *   <script src="https://YOUR-RAILWAY-URL/widget.js" data-client="haircutzforbreakupz"></script>
 *
 * Optional data attributes:
 *   data-client    — client ID (matches filename in /clients folder)
 *   data-accent    — override accent color (hex)
 *   data-position  — "bottom-right" (default) or "bottom-left"
 *   data-delay     — auto-open delay in ms (0 to disable, default 5000)
 */
(function () {
  "use strict";

  // --- Grab config from script tag ---
  const scriptTag = document.currentScript;
  const API_BASE = scriptTag.src.replace(/\/widget\.js.*$/, "");
  const CLIENT_ID = scriptTag.getAttribute("data-client") || "demo";
  const ACCENT = scriptTag.getAttribute("data-accent") || "#c8a84e";
  const POSITION = scriptTag.getAttribute("data-position") || "bottom-right";
  const AUTO_OPEN_DELAY = parseInt(scriptTag.getAttribute("data-delay") || "5000", 10);

  // --- State ---
  let isOpen = false;
  let messages = [];
  let isLoading = false;
  let config = { business_name: "Chat", greeting: "Hey! 👋 How can I help?", accent_color: ACCENT };

  // --- Load client config ---
  fetch(API_BASE + "/api/config", { headers: { "X-Client-ID": CLIENT_ID } })
    .then((r) => r.json())
    .then((data) => {
      config = { ...config, ...data };
      messages = [{ role: "assistant", content: config.greeting }];
      renderMessages();
      updateHeader();
    })
    .catch(() => {
      messages = [{ role: "assistant", content: config.greeting }];
    });

  // --- Inject fonts ---
  const fontLink = document.createElement("link");
  fontLink.rel = "stylesheet";
  fontLink.href = "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap";
  document.head.appendChild(fontLink);

  // --- Inject styles ---
  const style = document.createElement("style");
  style.textContent = `
    #ns-chat-widget * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'DM Sans', -apple-system, sans-serif; }
    #ns-chat-bubble {
      position: fixed; ${POSITION === "bottom-left" ? "left" : "right"}: 24px; bottom: 24px;
      width: 64px; height: 64px; border-radius: 50%; border: none; cursor: pointer;
      background: linear-gradient(135deg, ${ACCENT}, ${adjustColor(ACCENT, -30)});
      box-shadow: 0 4px 20px ${ACCENT}55;
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s; z-index: 99999;
    }
    #ns-chat-bubble:hover { transform: scale(1.08); box-shadow: 0 6px 28px ${ACCENT}77; }
    #ns-chat-bubble svg { width: 28px; height: 28px; stroke: #fff; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

    #ns-chat-window {
      position: fixed; ${POSITION === "bottom-left" ? "left" : "right"}: 24px; bottom: 100px;
      width: 380px; max-width: calc(100vw - 48px); height: 520px; max-height: calc(100vh - 140px);
      background: #111; border: 1px solid #2a2a2a; border-radius: 16px;
      display: none; flex-direction: column; overflow: hidden;
      box-shadow: 0 12px 48px rgba(0,0,0,0.6); z-index: 99998;
      animation: ns-slide-up 0.3s ease-out;
    }
    #ns-chat-window.ns-open { display: flex; }

    @keyframes ns-slide-up { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }

    #ns-chat-header {
      padding: 14px 16px; display: flex; align-items: center; gap: 10px;
      background: linear-gradient(135deg, #141428, #1a1a3a); border-bottom: 1px solid #2a2a2a;
    }
    #ns-chat-header .ns-avatar {
      width: 38px; height: 38px; border-radius: 50%;
      background: linear-gradient(135deg, ${ACCENT}, ${adjustColor(ACCENT, -30)});
      display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    #ns-chat-header .ns-info { flex: 1; }
    #ns-chat-header .ns-name { color: #fff; font-size: 15px; font-weight: 600; }
    #ns-chat-header .ns-status { color: #4ade80; font-size: 12px; display: flex; align-items: center; gap: 4px; }
    #ns-chat-header .ns-dot { width: 6px; height: 6px; border-radius: 50%; background: #4ade80; }
    #ns-chat-close { background: none; border: none; color: #666; font-size: 22px; cursor: pointer; padding: 4px; line-height: 1; }
    #ns-chat-close:hover { color: #aaa; }

    #ns-chat-messages {
      flex: 1; overflow-y: auto; padding: 16px 14px 8px; display: flex; flex-direction: column; gap: 10px;
    }
    #ns-chat-messages::-webkit-scrollbar { width: 5px; }
    #ns-chat-messages::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }

    .ns-msg { display: flex; }
    .ns-msg.ns-user { justify-content: flex-end; }
    .ns-msg.ns-bot { justify-content: flex-start; }
    .ns-msg .ns-bubble {
      max-width: 82%; padding: 10px 14px; font-size: 14px; line-height: 1.5; white-space: pre-wrap;
    }
    .ns-msg.ns-bot .ns-bubble { background: #1a1a2e; color: #e8e8e8; border-radius: 14px 14px 14px 4px; }
    .ns-msg.ns-user .ns-bubble { background: ${ACCENT}; color: #0a0a0a; border-radius: 14px 14px 4px 14px; font-weight: 500; }

    .ns-typing { display: flex; gap: 5px; padding: 12px 16px; background: #1a1a2e; border-radius: 14px 14px 14px 4px; width: fit-content; }
    .ns-typing span { width: 7px; height: 7px; border-radius: 50%; background: ${ACCENT}; animation: ns-pulse 1s ease-in-out infinite; }
    .ns-typing span:nth-child(2) { animation-delay: 0.15s; }
    .ns-typing span:nth-child(3) { animation-delay: 0.3s; }
    @keyframes ns-pulse { 0%,100% { opacity: 0.3; } 50% { opacity: 1; } }

    #ns-chat-inputbar {
      padding: 10px 14px; border-top: 1px solid #2a2a2a; display: flex; gap: 8px; background: #0a0a0a;
    }
    #ns-chat-input {
      flex: 1; background: #151515; border: 1px solid #2a2a2a; border-radius: 10px;
      padding: 10px 12px; color: #e8e8e8; font-size: 14px; outline: none; transition: border-color 0.2s;
    }
    #ns-chat-input:focus { border-color: ${ACCENT}; }
    #ns-chat-input::placeholder { color: #555; }

    #ns-chat-send {
      width: 40px; height: 40px; border-radius: 10px; background: ${ACCENT}; border: none;
      cursor: pointer; display: flex; align-items: center; justify-content: center; transition: opacity 0.2s;
    }
    #ns-chat-send:disabled { opacity: 0.35; cursor: default; }
    #ns-chat-send svg { width: 16px; height: 16px; stroke: #0a0a0a; fill: none; stroke-width: 2.5; stroke-linecap: round; }

    #ns-chat-footer {
      padding: 5px 14px 8px; text-align: center; font-size: 11px; color: #555; background: #0a0a0a;
    }
    #ns-chat-footer span { color: ${ACCENT}; font-weight: 600; }

    @media (max-width: 440px) {
      #ns-chat-window { width: calc(100vw - 16px); ${POSITION === "bottom-left" ? "left" : "right"}: 8px; bottom: 90px; height: calc(100vh - 110px); border-radius: 12px; }
      #ns-chat-bubble { ${POSITION === "bottom-left" ? "left" : "right"}: 16px; bottom: 16px; }
    }
  `;
  document.head.appendChild(style);

  // --- Build DOM ---
  const root = document.createElement("div");
  root.id = "ns-chat-widget";
  root.innerHTML = `
    <div id="ns-chat-window">
      <div id="ns-chat-header">
        <div class="ns-avatar">💬</div>
        <div class="ns-info">
          <div class="ns-name">${escHtml(config.business_name)}</div>
          <div class="ns-status"><span class="ns-dot"></span> Online — replies instantly</div>
        </div>
        <button id="ns-chat-close">&times;</button>
      </div>
      <div id="ns-chat-messages"></div>
      <div id="ns-chat-inputbar">
        <input id="ns-chat-input" placeholder="Ask a question or book an appointment..." autocomplete="off" />
        <button id="ns-chat-send" disabled>
          <svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        </button>
      </div>
      <div id="ns-chat-footer">⚡ Powered by <span>NovaShift</span></div>
    </div>
    <button id="ns-chat-bubble">
      <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    </button>
  `;
  document.body.appendChild(root);

  // --- Element refs ---
  const bubble = document.getElementById("ns-chat-bubble");
  const win = document.getElementById("ns-chat-window");
  const closeBtn = document.getElementById("ns-chat-close");
  const msgContainer = document.getElementById("ns-chat-messages");
  const input = document.getElementById("ns-chat-input");
  const sendBtn = document.getElementById("ns-chat-send");

  // --- Event handlers ---
  bubble.addEventListener("click", toggleWidget);
  closeBtn.addEventListener("click", () => setOpen(false));
  input.addEventListener("input", () => { sendBtn.disabled = !input.value.trim() || isLoading; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
  sendBtn.addEventListener("click", sendMessage);

  // Auto-open after delay
  if (AUTO_OPEN_DELAY > 0) {
    setTimeout(() => { if (!isOpen) setOpen(true); }, AUTO_OPEN_DELAY);
  }

  // --- Functions ---
  function toggleWidget() { setOpen(!isOpen); }

  function setOpen(val) {
    isOpen = val;
    win.classList.toggle("ns-open", isOpen);
    bubble.innerHTML = isOpen
      ? '<svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
      : '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
    if (isOpen) input.focus();
  }

  function updateHeader() {
    const nameEl = root.querySelector(".ns-name");
    if (nameEl) nameEl.textContent = config.business_name;
  }

  function renderMessages() {
    let html = "";
    for (const m of messages) {
      const cls = m.role === "user" ? "ns-user" : "ns-bot";
      html += `<div class="ns-msg ${cls}"><div class="ns-bubble">${escHtml(m.content)}</div></div>`;
    }
    if (isLoading) {
      html += '<div class="ns-msg ns-bot"><div class="ns-typing"><span></span><span></span><span></span></div></div>';
    }
    msgContainer.innerHTML = html;
    msgContainer.scrollTop = msgContainer.scrollHeight;
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text || isLoading) return;

    messages.push({ role: "user", content: text });
    input.value = "";
    sendBtn.disabled = true;
    isLoading = true;
    renderMessages();

    try {
      const res = await fetch(API_BASE + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Client-ID": CLIENT_ID },
        body: JSON.stringify({ messages: messages })
      });
      const data = await res.json();
      messages.push({ role: "assistant", content: data.reply || "Sorry, I hit a snag. Try again?" });
    } catch (err) {
      messages.push({ role: "assistant", content: "Connection issue — give it another shot." });
    }

    isLoading = false;
    renderMessages();
    input.focus();
  }

  function escHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }

  function adjustColor(hex, amt) {
    hex = hex.replace("#", "");
    let r = Math.max(0, Math.min(255, parseInt(hex.substring(0, 2), 16) + amt));
    let g = Math.max(0, Math.min(255, parseInt(hex.substring(2, 4), 16) + amt));
    let b = Math.max(0, Math.min(255, parseInt(hex.substring(4, 6), 16) + amt));
    return "#" + [r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("");
  }
})();
