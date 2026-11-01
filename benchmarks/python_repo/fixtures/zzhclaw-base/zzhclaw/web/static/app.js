/* ===== ZzhClaw Web UI 前端逻辑 ===== */

// ===== 全局状态 =====
const state = {
    ws: null,
    connected: false,
    currentSessionId: null,
    sessions: [],
    isProcessing: false,
    theme: localStorage.getItem('zzhclaw-theme') || 'light',
    sidebarCollapsed: localStorage.getItem('zzhclaw-sidebar') === 'collapsed',
    // 流式输出状态
    streamingEl: null,      // 当前流式 AI 气泡元素
    streamingText: '',      // 累积的流式文本
    // 权限模式
    permissionMode: 'confirm',
};

// ===== 权限模式配置 =====
const PERMISSION_MODES = {
    confirm: { icon: '🔒', label: 'confirm', desc: '每个工具都确认' },
    smart:   { icon: '⚡', label: 'smart', desc: '只读自动，写/执行确认' },
    auto:    { icon: '🤖', label: 'auto', desc: '全自动，不再询问' },
};
const PERMISSION_ORDER = ['confirm', 'smart', 'auto'];

// ===== DOM 引用 =====
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    sidebar: $('#sidebar'),
    sessionList: $('#session-list'),
    messagesList: $('#messages-list'),
    messagesContainer: $('#messages-container'),
    welcomeScreen: $('#welcome-screen'),
    userInput: $('#user-input'),
    btnSend: $('#btn-send'),
    btnNewChat: $('#btn-new-chat'),
    btnCollapse: $('#btn-collapse'),
    btnMenu: $('#btn-menu'),
    btnTheme: $('#btn-theme'),
    btnSave: $('#btn-save'),
    btnPermission: $('#btn-permission'),
    permIcon: $('#perm-icon'),
    permLabel: $('#perm-label'),
    chatTitle: $('#chat-title'),
    modelInfo: $('#model-info'),
    confirmModal: $('#confirm-modal'),
    confirmToolName: $('#confirm-tool-name'),
    confirmToolArgs: $('#confirm-tool-args'),
    btnConfirmYes: $('#btn-confirm-yes'),
    btnConfirmNo: $('#btn-confirm-no'),
    toast: $('#toast'),
};

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    applyTheme();
    applySidebarState();
    setupMarked();
    bindEvents();
    connectWebSocket();
    loadSessions();
});

// ===== Markdown 配置 =====
function setupMarked() {
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                try { return hljs.highlight(code, { language: lang }).value; }
                catch (e) {}
            }
            try { return hljs.highlightAuto(code).value; }
            catch (e) {}
            return code;
        }
    });
}

// ===== WebSocket =====
function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    state.ws = new WebSocket(`${protocol}//${location.host}/ws`);

    state.ws.onopen = () => {
        state.connected = true;
        showToast('已连接');
    };

    state.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
    };

    state.ws.onclose = () => {
        state.connected = false;
        showToast('连接断开，3 秒后重连...');
        setTimeout(connectWebSocket, 3000);
    };

    state.ws.onerror = () => {
        showToast('连接错误');
    };
}

function sendToServer(data) {
    if (state.ws && state.connected) {
        state.ws.send(JSON.stringify(data));
    }
}

// ===== 处理服务器消息 =====
function handleServerMessage(data) {
    switch (data.type) {
        case 'token':
            handleStreamToken(data.content);
            break;

        case 'assistant_message':
            hideTypingIndicator();
            finalizeStreamingBubble(data.content);
            state.isProcessing = false;
            updateSendButton();
            if (data.session_id) {
                state.currentSessionId = data.session_id;
                loadSessions(); // 刷新列表（消息数变了）
            }
            break;

        case 'tool_call':
            closeStreamingBubble();
            appendToolPanel(data.name, data.args, 'calling');
            break;

        case 'tool_result':
            updateLastToolPanel(data.name, data.result, data.full_length);
            break;

        case 'confirm_request':
            showConfirmModal(data.name, data.args);
            break;

        case 'session_created':
            state.currentSessionId = data.session_id;
            dom.chatTitle.textContent = data.name;
            loadSessions();
            break;

        case 'session_loaded':
            state.currentSessionId = data.session_id;
            dom.chatTitle.textContent = data.name;
            renderLoadedMessages(data.messages);
            loadSessions();
            break;

        case 'saved':
            showToast('会话已保存');
            break;

        case 'system_message':
            appendSystemMessage(data.content);
            break;

        case 'permission_mode':
            state.permissionMode = data.mode;
            updatePermissionButton();
            break;

        case 'error':
            hideTypingIndicator();
            cleanupStreaming();
            appendSystemMessage(`错误: ${data.message}`);
            state.isProcessing = false;
            updateSendButton();
            break;

        case 'pong':
            break;
    }
}

// ===== 消息渲染 =====
function appendMessage(role, content) {
    hideWelcome();
    const msgEl = createMessageElement(role, content);
    dom.messagesList.appendChild(msgEl);
    scrollToBottom();
}

// ===== 流式输出渲染 =====
function handleStreamToken(delta) {
    hideWelcome();
    // 第一个 token：移除"思考中"动画，创建流式气泡
    if (!state.streamingEl) {
        hideTypingIndicator();
        state.streamingEl = createStreamingBubble();
        state.streamingText = '';
        dom.messagesList.appendChild(state.streamingEl);
    }
    state.streamingText += delta;
    // 更新气泡文本（纯文本打字机效果，完成后才渲染 Markdown）
    const textSpan = state.streamingEl.querySelector('.stream-text');
    if (textSpan) textSpan.textContent = state.streamingText;
    scrollToBottom();
}

function createStreamingBubble() {
    const wrap = document.createElement('div');
    wrap.className = 'message assistant';
    wrap.innerHTML = `
        <div class="message-avatar">🐾</div>
        <div class="message-content">
            <div class="message-bubble"><span class="stream-text"></span><span class="stream-cursor">▊</span></div>
            <div class="message-time">${formatTime(new Date())}</div>
        </div>
    `;
    return wrap;
}

function finalizeStreamingBubble(fullContent) {
    if (!state.streamingEl) {
        // 没有流式气泡（纯工具调用无文本回复），创建普通 Markdown 消息
        if (fullContent) appendMessage('assistant', fullContent);
        return;
    }
    const bubble = state.streamingEl.querySelector('.message-bubble');
    // 用完整内容渲染 Markdown（替换纯文本 + 移除光标）
    bubble.innerHTML = renderMarkdown(fullContent);
    enhanceCodeBlocks(bubble);
    state.streamingEl = null;
    state.streamingText = '';
    scrollToBottom();
}

function cleanupStreaming() {
    // 异常时清理未完成的流式气泡
    if (state.streamingEl) {
        state.streamingEl.remove();
        state.streamingEl = null;
        state.streamingText = '';
    }
}

function closeStreamingBubble() {
    // 工具调用边界：定型当前流式气泡（渲染已累积文本为 Markdown），下轮 token 新建气泡
    if (state.streamingEl) {
        const bubble = state.streamingEl.querySelector('.message-bubble');
        bubble.innerHTML = renderMarkdown(state.streamingText);
        enhanceCodeBlocks(bubble);
        state.streamingEl = null;
        state.streamingText = '';
    }
}

function appendSystemMessage(text) {
    hideWelcome();
    const el = document.createElement('div');
    el.className = 'system-message';
    el.style.cssText = 'text-align:center;color:var(--text-tertiary);font-size:13px;padding:8px;';
    el.textContent = text;
    dom.messagesList.appendChild(el);
    scrollToBottom();
}

function createMessageElement(role, content) {
    const wrap = document.createElement('div');
    wrap.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '👤' : '🐾';

    const contentWrap = document.createElement('div');
    contentWrap.className = 'message-content';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    if (role === 'assistant') {
        bubble.innerHTML = renderMarkdown(content);
        // 渲染后处理代码块（加 header + 复制按钮）
        enhanceCodeBlocks(bubble);
    } else {
        bubble.textContent = content;
    }

    const time = document.createElement('div');
    time.className = 'message-time';
    time.textContent = formatTime(new Date());

    contentWrap.appendChild(bubble);
    contentWrap.appendChild(time);
    wrap.appendChild(avatar);
    wrap.appendChild(contentWrap);
    return wrap;
}

function renderMarkdown(text) {
    if (!text) return '';
    try {
        return marked.parse(text);
    } catch (e) {
        return escapeHtml(text);
    }
}

function enhanceCodeBlocks(container) {
    container.querySelectorAll('pre code').forEach((codeEl) => {
        const pre = codeEl.parentElement;
        if (pre.querySelector('.code-header')) return; // 已处理

        // 推断语言
        let lang = '';
        codeEl.classList.forEach((cls) => {
            if (cls.startsWith('language-')) lang = cls.replace('language-', '');
        });
        if (!lang) lang = 'code';

        const header = document.createElement('div');
        header.className = 'code-header';
        header.innerHTML = `
            <span class="code-lang">${escapeHtml(lang)}</span>
            <button class="btn-copy" onclick="copyCode(this)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2"/>
                    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
                </svg>
                复制
            </button>
        `;
        pre.insertBefore(header, codeEl);
    });
}

// 全局复制函数（供 onclick 调用）
window.copyCode = function(btn) {
    const pre = btn.closest('pre');
    const code = pre.querySelector('code');
    navigator.clipboard.writeText(code.textContent).then(() => {
        btn.classList.add('copied');
        btn.querySelector('svg').style.display = 'none';
        const originalText = btn.childNodes[btn.childNodes.length - 1];
        originalText.textContent = ' 已复制';
        setTimeout(() => {
            btn.classList.remove('copied');
            btn.querySelector('svg').style.display = '';
            originalText.textContent = ' 复制';
        }, 2000);
    });
};

function renderLoadedMessages(messages) {
    dom.messagesList.innerHTML = '';
    if (!messages || messages.length === 0) {
        showWelcome();
        return;
    }
    hideWelcome();
    messages.forEach((m) => {
        if (m.role === 'system') return;
        if (m.role === 'tool') {
            // 工具结果合并到上一个 tool panel（简化：跳过独立渲染）
            return;
        }
        if (m.role === 'assistant' && m.tool_calls) {
            // assistant 带 tool_calls：渲染工具面板
            m.tool_calls.forEach((tc) => {
                let args = {};
                try { args = JSON.parse(tc.function.arguments || '{}'); } catch (e) {}
                appendToolPanel(tc.function.name, args, 'done');
            });
            if (m.content) appendMessage('assistant', m.content);
        } else {
            appendMessage(m.role, m.content);
        }
    });
    scrollToBottom();
}

// ===== 工具面板 =====
function appendToolPanel(name, args, status) {
    hideWelcome();
    const panel = document.createElement('div');
    panel.className = 'tool-panel';
    panel.dataset.toolName = name;
    panel.dataset.status = status;

    const statusText = status === 'calling' ? '执行中...' : '已完成';
    const icon = getToolIcon(name);

    panel.innerHTML = `
        <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="tool-icon">${icon}</span>
            <span class="tool-name-badge">${escapeHtml(name)}</span>
            <span class="tool-status">${statusText}</span>
        </div>
        <div class="tool-body">
            <div class="tool-section">
                <div class="tool-section-label">参数</div>
                <pre>${escapeHtml(JSON.stringify(args, null, 2))}</pre>
            </div>
            <div class="tool-section tool-result-section" style="display:none;">
                <div class="tool-section-label">结果</div>
                <pre class="tool-result-content"></pre>
            </div>
        </div>
    `;
    dom.messagesList.appendChild(panel);
    scrollToBottom();
}

function updateLastToolPanel(name, result, fullLength) {
    // 找到最后一个匹配的 tool panel
    const panels = dom.messagesList.querySelectorAll(`.tool-panel[data-tool-name="${name}"]`);
    const panel = panels[panels.length - 1];
    if (!panel) return;

    panel.dataset.status = 'done';
    panel.querySelector('.tool-status').textContent = '已完成';

    const resultSection = panel.querySelector('.tool-result-section');
    const resultContent = panel.querySelector('.tool-result-content');
    resultSection.style.display = '';
    resultContent.textContent = result;
    if (fullLength > result.length) {
        resultContent.textContent += `\n\n(已截断，完整长度 ${fullLength} 字符)`;
    }
}

function getToolIcon(name) {
    const icons = {
        'read_file': '📖',
        'write_file': '✏️',
        'edit_file': '📝',
        'run_bash': '💻',
        'web_search': '🔍',
        'fetch_webpage': '🌐',
        'grep_files': '🔎',
        'glob_files': '📂',
    };
    return icons[name] || '🔧';
}

// ===== 确认弹窗 =====
function showConfirmModal(name, args) {
    dom.confirmToolName.textContent = name;
    dom.confirmToolArgs.textContent = JSON.stringify(args, null, 2);
    dom.confirmModal.style.display = 'flex';
}

function hideConfirmModal() {
    dom.confirmModal.style.display = 'none';
}

function respondConfirm(approved) {
    sendToServer({ type: 'confirm', approved });
    hideConfirmModal();
}

// ===== 会话管理 =====
async function loadSessions() {
    try {
        const res = await fetch('/api/sessions');
        state.sessions = await res.json();
        renderSessionList();
    } catch (e) {
        console.error('加载会话列表失败:', e);
    }
}

function renderSessionList() {
    dom.sessionList.innerHTML = '';
    if (state.sessions.length === 0) {
        dom.sessionList.innerHTML = '<div style="text-align:center;color:var(--text-tertiary);padding:20px;font-size:13px;">暂无会话</div>';
        return;
    }
    state.sessions.forEach((s) => {
        const item = document.createElement('div');
        item.className = 'session-item' + (s.id === state.currentSessionId ? ' active' : '');
        item.innerHTML = `
            <div class="session-item-content" onclick="switchSession('${s.id}')">
                <div class="session-item-name">${escapeHtml(s.name)}</div>
                <div class="session-item-meta">${s.messages} 条消息 · ${formatDate(s.created_at)}</div>
            </div>
            <div class="session-item-actions">
                <button class="btn-icon" onclick="event.stopPropagation();renameSession('${s.id}','${escapeHtml(s.name)}')" title="重命名">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17 3a2.828 2.828 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>
                    </svg>
                </button>
                <button class="btn-icon" onclick="event.stopPropagation();deleteSession('${s.id}')" title="删除">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3,6 5,6 21,6"/>
                        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                    </svg>
                </button>
            </div>
        `;
        dom.sessionList.appendChild(item);
    });
}

window.switchSession = function(sessionId) {
    sendToServer({ type: 'load_session', session_id: sessionId });
    dom.messagesList.innerHTML = '';
    showWelcome();
};

window.deleteSession = async function(sessionId) {
    if (!confirm('确定删除这个会话吗？')) return;
    try {
        await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        if (state.currentSessionId === sessionId) {
            state.currentSessionId = null;
            dom.chatTitle.textContent = '新对话';
            dom.messagesList.innerHTML = '';
            showWelcome();
        }
        loadSessions();
        showToast('已删除');
    } catch (e) {
        showToast('删除失败');
    }
};

window.renameSession = async function(sessionId, currentName) {
    const newName = prompt('输入新名称:', currentName);
    if (!newName || newName === currentName) return;
    try {
        await fetch(`/api/sessions/${sessionId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName }),
        });
        loadSessions();
        if (state.currentSessionId === sessionId) {
            dom.chatTitle.textContent = newName;
        }
        showToast('已重命名');
    } catch (e) {
        showToast('重命名失败');
    }
};

function newChat() {
    state.currentSessionId = null;
    dom.chatTitle.textContent = '新对话';
    dom.messagesList.innerHTML = '';
    showWelcome();
    sendToServer({ type: 'new_session' });
}

// ===== 发送消息 =====
function sendMessage() {
    const text = dom.userInput.value.trim();
    if (!text || state.isProcessing) return;

    appendMessage('user', text);
    dom.userInput.value = '';
    autoResizeInput();

    // 重置流式状态
    cleanupStreaming();

    state.isProcessing = true;
    updateSendButton();
    showTypingIndicator();

    sendToServer({ type: 'chat', message: text });
}

function showTypingIndicator() {
    hideTypingIndicator();
    const el = document.createElement('div');
    el.className = 'message assistant';
    el.id = 'typing-indicator';
    el.innerHTML = `
        <div class="message-avatar">🐾</div>
        <div class="message-content">
            <div class="message-bubble">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `;
    dom.messagesList.appendChild(el);
    scrollToBottom();
}

function hideTypingIndicator() {
    const el = $('#typing-indicator');
    if (el) el.remove();
}

function updateSendButton() {
    dom.btnSend.disabled = state.isProcessing || !dom.userInput.value.trim();
}

// ===== 输入处理 =====
function autoResizeInput() {
    dom.userInput.style.height = 'auto';
    dom.userInput.style.height = Math.min(dom.userInput.scrollHeight, 200) + 'px';
}

// ===== 主题 =====
function applyTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
}

function toggleTheme() {
    state.theme = state.theme === 'light' ? 'dark' : 'light';
    localStorage.setItem('zzhclaw-theme', state.theme);
    applyTheme();
}

// ===== 权限模式 =====
function updatePermissionButton() {
    const mode = state.permissionMode || 'confirm';
    const cfg = PERMISSION_MODES[mode] || PERMISSION_MODES.confirm;
    dom.permIcon.textContent = cfg.icon;
    dom.permLabel.textContent = cfg.label;
    dom.btnPermission.className = 'btn-permission perm-' + mode;
    dom.btnPermission.title = `权限模式: ${mode}（${cfg.desc}）— 点击切换`;
}

function cyclePermissionMode() {
    const current = state.permissionMode || 'confirm';
    const idx = PERMISSION_ORDER.indexOf(current);
    const next = PERMISSION_ORDER[(idx + 1) % PERMISSION_ORDER.length];
    sendToServer({ type: 'set_permission', mode: next });
    showToast(`权限模式 → ${next}（${PERMISSION_MODES[next].desc}）`);
}

// ===== 侧边栏 =====
function applySidebarState() {
    if (state.sidebarCollapsed) {
        dom.sidebar.classList.add('collapsed');
    }
}

function toggleSidebar() {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    dom.sidebar.classList.toggle('collapsed');
    localStorage.setItem('zzhclaw-sidebar', state.sidebarCollapsed ? 'collapsed' : 'expanded');
}

// ===== 欢迎屏 =====
function showWelcome() {
    dom.welcomeScreen.style.display = 'flex';
}

function hideWelcome() {
    dom.welcomeScreen.style.display = 'none';
}

// ===== 工具函数 =====
function scrollToBottom() {
    requestAnimationFrame(() => {
        dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(date) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function formatDate(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    if (isToday) return formatTime(d);
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function showToast(msg, duration = 2500) {
    dom.toast.textContent = msg;
    dom.toast.style.display = 'block';
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => {
        dom.toast.style.display = 'none';
    }, duration);
}

// ===== 事件绑定 =====
function bindEvents() {
    // 发送
    dom.btnSend.addEventListener('click', sendMessage);
    dom.userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    dom.userInput.addEventListener('input', () => {
        autoResizeInput();
        updateSendButton();
    });

    // 新建对话
    dom.btnNewChat.addEventListener('click', newChat);

    // 侧边栏
    dom.btnCollapse.addEventListener('click', toggleSidebar);
    dom.btnMenu.addEventListener('click', toggleSidebar);

    // 主题
    dom.btnTheme.addEventListener('click', toggleTheme);

    // 保存
    dom.btnSave.addEventListener('click', () => sendToServer({ type: 'save_session' }));

    // 权限模式切换（点击循环 confirm → smart → auto）
    dom.btnPermission.addEventListener('click', cyclePermissionMode);

    // 确认弹窗
    dom.btnConfirmYes.addEventListener('click', () => respondConfirm(true));
    dom.btnConfirmNo.addEventListener('click', () => respondConfirm(false));

    // 建议卡片
    $$('.suggestion-card').forEach((card) => {
        card.addEventListener('click', () => {
            const prompt = card.dataset.prompt;
            dom.userInput.value = prompt;
            autoResizeInput();
            updateSendButton();
            sendMessage();
        });
    });

    // 键盘快捷键
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + K: 新建对话
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            newChat();
        }
        // Ctrl/Cmd + B: 切换侧边栏
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            toggleSidebar();
        }
        // Ctrl/Cmd + Shift + L: 切换主题
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'L') {
            e.preventDefault();
            toggleTheme();
        }
        // Escape: 关闭弹窗
        if (e.key === 'Escape' && dom.confirmModal.style.display === 'flex') {
            respondConfirm(false);
        }
    });

    // 心跳保活
    setInterval(() => {
        if (state.connected) sendToServer({ type: 'ping' });
    }, 30000);
}
