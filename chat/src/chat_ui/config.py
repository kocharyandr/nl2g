import os

API_BASE = os.getenv("CHART_AGENT_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = int(os.getenv("CHAT_REQUEST_TIMEOUT", "120"))

APP_CSS = """
/* Оформление под отчёты: те же токены, пузыри переписки, блоки SQL и таблицы.
   Светлая и тёмная темы задаются одними переменными и следуют системной. */
:root {
  --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --bg: #f9f9f7; --card: #fcfcfb; --bbg: #ffffff;
  --line: rgba(11,11,11,.10); --grid: #e1e0d9;
  --accent: #2a78d6; --accent-ink: #fff;
  --ok: #0ca30c; --bad: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ink: #fff; --ink2: #c3c2b7; --muted: #898781;
    --bg: #0d0d0d; --card: #1a1a19; --bbg: #242423;
    --line: rgba(255,255,255,.10); --grid: #2c2c2a;
    --accent: #3987e5;
  }
}

/* Перекрываем собственные переменные Gradio — иначе его оранжевый акцент
   побеждает по специфичности на кнопках, галочках и фокусе. */
.gradio-container, :root {
  --color-accent: var(--accent) !important;
  --color-accent-base: var(--accent) !important;
  --button-primary-background-fill: var(--accent) !important;
  --button-primary-background-fill-hover: var(--accent) !important;
  --button-primary-border-color: var(--accent) !important;
  --button-primary-text-color: #fff !important;
  --checkbox-background-color-selected: var(--accent) !important;
  --checkbox-border-color-selected: var(--accent) !important;
  --body-background-fill: var(--bg) !important;
  --background-fill-primary: var(--bg) !important;
  --block-background-fill: var(--card) !important;
  --body-text-color: var(--ink) !important;
  --body-text-color-subdued: var(--muted) !important;
  --border-color-primary: var(--line) !important;
  --input-background-fill: var(--card) !important;
}

/* Служебные надписи Gradio: подписи компонентов и нижняя панель. */
footer, .gradio-container footer, div[class*="built-with"], div[class*="api-docs"],
.gradio-container > .main > .wrap > div:last-child > div[class*="footer"] { display: none !important; }
#chatbot label, #chat_input > label, #chatbot .label-wrap, #chat_input .label-wrap,
#chatbot > .block-label, #chatbot span[data-testid="block-info"],
#chat_input span[data-testid="block-info"] { display: none !important; }

@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.35;transform:scale(.88)} }
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
@keyframes spin  { from{transform:rotate(0)} to{transform:rotate(360deg)} }

footer { display: none !important; }
gradio-app, .gradio-container {
  height: 100vh !important; max-width: 100% !important;
  margin: 0 !important; padding: 0 !important;
  background: var(--bg) !important; color: var(--ink) !important;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif !important;
}
.gradio-container > .main > .wrap { height: 100% !important; flex: 1 1 auto !important; }
.gradio-container .block, .gradio-container .form { background: transparent !important; border: none !important; }

/* ── лента сообщений ─────────────────────────────────────────── */
#chatbot { flex: 1 1 auto !important; min-height: 0 !important;
  background: var(--bg) !important; border: none !important; }
#chatbot .wrap { height: 100% !important; }
#chatbot .message-wrap { max-width: 1000px; margin: 0 auto; padding: 8px 14px 4px; }

#chatbot .message-row { margin: 10px 0 !important; }
#chatbot .message {
  border-radius: 16px !important;
  padding: 10px 14px !important;
  font-size: 14.5px !important;
  line-height: 1.5 !important;
  box-shadow: none !important;
  max-width: 88% !important;
}
#chatbot .user-row .message, #chatbot .message.user {
  background: var(--accent) !important;
  color: var(--accent-ink) !important;
  border: none !important;
  border-bottom-right-radius: 5px !important;
}
#chatbot .user-row .message *, #chatbot .message.user * { color: var(--accent-ink) !important; }
#chatbot .bot-row .message, #chatbot .message.bot {
  background: var(--bbg) !important;
  color: var(--ink) !important;
  border: 1px solid var(--line) !important;
  border-bottom-left-radius: 5px !important;
  max-width: 94% !important;
}

/* ── содержимое ответов: SQL, код, таблицы, картинки ─────────── */
#chatbot .message pre, #chatbot .message code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace !important;
}
#chatbot .bot-row .message pre {
  background: var(--bg) !important;
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  padding: 10px 12px !important;
  font-size: 12.5px !important;
  line-height: 1.5 !important;
  overflow-x: auto !important;
  white-space: pre-wrap !important;
  word-break: break-word !important;
}
#chatbot .bot-row .message :not(pre) > code {
  background: rgba(42,120,214,.10) !important;
  border-radius: 4px !important; padding: 1px 5px !important; font-size: .88em !important;
}
#chatbot .message img {
  border-radius: 10px !important;
  border: 1px solid var(--grid) !important;
  background: #fff !important;
  margin-top: 8px !important;
}
#chatbot .message table {
  border-collapse: collapse !important; font-size: 13px !important; margin-top: 8px !important;
}
#chatbot .message th, #chatbot .message td {
  border: none !important; border-bottom: 1px solid var(--grid) !important;
  padding: 5px 12px 5px 0 !important; text-align: left !important;
}
#chatbot .message th {
  font-size: 11px !important; text-transform: uppercase !important;
  letter-spacing: .06em !important; color: var(--muted) !important;
}
#chatbot .message details { margin-top: 10px !important; font-size: 13px !important; }
#chatbot .message summary { cursor: pointer !important; color: var(--accent) !important; }
#chatbot .message small { color: var(--muted) !important; font-size: 12px !important; }

/* ── поле ввода и кнопки ─────────────────────────────────────── */
#chat_input textarea {
  border-radius: 16px !important;
  border: 1px solid var(--line) !important;
  background: var(--card) !important;
  color: var(--ink) !important;
  padding: 12px 14px !important;
  font-size: 14.5px !important;
}
#chat_input textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px rgba(42,120,214,.16) !important;
}
#send_btn button {
  border-radius: 12px !important;
  background: var(--accent) !important;
  border: 1px solid var(--accent) !important;
  color: #fff !important;
  font-weight: 600 !important;
}
#send_btn button:hover { filter: brightness(1.06); }
#approve_btn button {
  background: var(--ok) !important; border: 1px solid var(--ok) !important;
  color: #fff !important; border-radius: 12px !important;
}
#approve_btn button:hover { filter: brightness(.95); }
#cancel_btn button {
  background: transparent !important; border: 1px solid var(--line) !important;
  color: var(--muted) !important; border-radius: 12px !important;
}
#cancel_btn button:hover { border-color: var(--bad) !important; color: var(--bad) !important; }

/* галочки и выпадающий список источника данных */
.gradio-container label, .gradio-container .info, .gradio-container span {
  color: var(--ink2) !important;
}
.gradio-container input[type="checkbox"] { accent-color: var(--accent) !important; }
.gradio-container select, .gradio-container .wrap-inner {
  background: var(--card) !important; color: var(--ink) !important;
  border: 1px solid var(--line) !important; border-radius: 8px !important;
}
"""

ENTER_SUBMIT_JS = """
() => {
  const root = document;
  if (window.__chat_enter_bound__) return;
  window.__chat_enter_bound__ = true;

  root.addEventListener("keydown", (e) => {
    const target = e.target;
    if (!(target instanceof HTMLTextAreaElement)) return;
    if (!target.closest("#chat_input")) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const sendBtn = document.querySelector("#send_btn button");
      if (sendBtn) sendBtn.click();
    }
  });

  // Override clipboard.writeText so that HTML content is stripped to plain text.
  // Elements marked with data-copy-skip (e.g. the CSV chip) are excluded entirely.
  if (!navigator.clipboard._chatPatched) {
    const _orig = navigator.clipboard.writeText.bind(navigator.clipboard);
    navigator.clipboard.writeText = function(text) {
      if (!text || !text.includes('<')) return _orig(text);
      const div = document.createElement('div');
      div.innerHTML = text;
      div.querySelectorAll('[data-copy-skip]').forEach(el => el.remove());
      const plain = (div.innerText || div.textContent || '').replace(/\\n{2,}/g, '\\n').trim();
      return _orig(plain || text);
    };
    navigator.clipboard._chatPatched = true;
  }
}
"""
