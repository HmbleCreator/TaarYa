/* ======================================================
   TaarYa — Frontend Application Logic
   Connects to FastAPI backend at /api/*
   ====================================================== */

const API = '';  // same origin — works for both web and desktop

// ---- Stars Background ----
function initStars() {
    const bg = document.getElementById('starsBg');
    if (!bg) return;
    for (let i = 0; i < 80; i++) {
        const star = document.createElement('div');
        star.className = 'star';
        const size = Math.random() * 2 + 1;
        star.style.width = size + 'px';
        star.style.height = size + 'px';
        star.style.left = Math.random() * 100 + '%';
        star.style.top = Math.random() * 100 + '%';
        star.style.setProperty('--dur', (Math.random() * 4 + 2) + 's');
        star.style.animationDelay = Math.random() * 4 + 's';
        bg.appendChild(star);
    }
}

// ---- Tab Navigation ----
function initTabs() {
    document.querySelectorAll('.nav-btn[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            const panel = document.getElementById('panel' + capitalize(btn.dataset.tab));
            if (panel) panel.classList.add('active');

            // Auto-load stats when System tab is opened
            if (btn.dataset.tab === 'stats') loadStats();
        });
    });
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ---- Chat ----
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
let chatHistory = [];

// Load history from session
// Load history from session and Render
try {
    const saved = localStorage.getItem('taarya_chat_history'); // Switch to localStorage for better persistence
    if (saved) {
        chatHistory = JSON.parse(saved);
        chatHistory.forEach(msg => {
            // Map 'human' -> 'user', 'ai' -> 'assistant'
            const role = (msg.role === 'human' || msg.role === 'user') ? 'user' : 'assistant';
            appendMessage(role, msg.content, null, false); // false = no scroll animation?
        });
        // Scroll to bottom
        setTimeout(() => chatMessages.scrollTop = chatMessages.scrollHeight, 100);
    }
} catch (e) { console.error("History load error", e); }

function sendSuggestion(el) {
    if (el.disabled) return;
    el.disabled = true;
    setTimeout(() => el.disabled = false, 1000); // Re-enable after 1s

    const text = el.textContent.trim();
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.value = text;
        sendMessage();
    } else {
        // Redirect to dashboard with query
        window.location.href = '/?q=' + encodeURIComponent(text);
    }
}

async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = '';

    // Add user message
    appendMessage('user', text);

    // Show typing indicator
    const typingEl = appendTyping();

    // Disable send button
    const sendBtn = document.getElementById('chatSend');
    sendBtn.disabled = true;

    try {
        // Try the agent endpoint first (LLM-powered)
        let data;
        try {
            const resp = await fetch(API + '/api/agent/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: text,
                    chat_history: chatHistory
                }),
            });
            data = await resp.json();
        } catch (e) {
            // Fallback: try direct search based on input
            data = await fallbackSearch(text);
        }

        typingEl.remove();

        if (data && data.answer) { // Ensure data exists and has answer
            // Pass tool_outputs to appendMessage
            appendMessage('assistant', data.answer, data.tools_used, true, data.tool_outputs);

            // Update history with tool_outputs
            chatHistory.push({ role: 'human', content: text });
            chatHistory.push({ role: 'ai', content: data.answer, tool_outputs: data.tool_outputs });

        } else if (data && data.error) {
            appendMessage('assistant', '⚠️ ' + data.error);
        } else {
            // Fallback result display
            const resultText = formatSearchResult(data);
            appendMessage('assistant', resultText);
            // Update history (approximate)
            chatHistory.push({ role: 'human', content: text });
            chatHistory.push({ role: 'ai', content: resultText });
        }

        // Limit & Save
        if (chatHistory.length > 50) chatHistory = chatHistory.slice(-50); // Increased limit
        localStorage.setItem('taarya_chat_history', JSON.stringify(chatHistory));

    } catch (err) {
        typingEl.remove();
        appendMessage('assistant', '❌ Failed to reach server: ' + err.message);
    }

    sendBtn.disabled = false;
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function fallbackSearch(text) {
    // Parse coordinates from text
    const raMatch = text.match(/ra\s*[=:]\s*([\d.]+)/i);
    const decMatch = text.match(/dec\s*[=:]\s*([+-]?[\d.]+)/i);
    const idMatch = text.match(/(?:star|source_id|id)\s*[=:]*\s*(\d{5,})/i);

    if (raMatch && decMatch) {
        const ra = parseFloat(raMatch[1]);
        const dec = parseFloat(decMatch[1]);
        const resp = await fetch(API + `/api/stars/cone-search?ra=${ra}&dec=${dec}&radius=0.5&limit=10`);
        return await resp.json();
    }

    if (idMatch) {
        const resp = await fetch(API + `/api/stars/lookup/${idMatch[1]}`);
        return await resp.json();
    }

    return { answer: "I couldn't parse your query. Try providing coordinates like 'RA=45, Dec=0.5' or a star ID." };
}

function appendMessage(role, text, toolsUsed, animate = true, toolOutputs = null) {
    const div = document.createElement('div');
    div.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'assistant' ? '✦' : '👤';

    const content = document.createElement('div');
    content.className = 'message-content';

    const textDiv = document.createElement('div');
    textDiv.className = 'message-text prose prose-invert max-w-none';

    // Safely parse markdown
    if (typeof marked !== 'undefined') {
        textDiv.innerHTML = marked.parse(text);
    } else {
        textDiv.innerHTML = formatText(text); // Fallback
    }

    // Show tools used
    if (toolsUsed && toolsUsed.length > 0) {
        const toolsDiv = document.createElement('div');
        toolsDiv.className = 'tools-used mt-2 text-xs text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-white/10 pt-2';
        toolsDiv.innerHTML = 'Tools: ' + toolsUsed.map(t =>
            `<span class="bg-gray-100 dark:bg-white/5 px-1 rounded mx-1" title="${t.input}">${t.tool}</span>`
        ).join(' ');
        textDiv.appendChild(toolsDiv);
    }

    // Show download button if tool outputs exist
    if (toolOutputs && toolOutputs.length > 0) {
        const starData = toolOutputs.find(t => Array.isArray(t.data) && t.data.length > 0);
        if (starData) {
            const btn = document.createElement('button');
            btn.className = 'mt-3 text-xs bg-primary/10 text-primary px-3 py-1.5 rounded-md hover:bg-primary/20 flex items-center gap-2 transition-colors border border-primary/20';
            btn.innerHTML = '<span class="material-icons text-[14px]">download</span> Export Data (JSON)';
            btn.onclick = () => downloadData(starData.data, `taarya_export_${Date.now()}.json`);
            textDiv.appendChild(btn);
        }
    }

    content.appendChild(textDiv);
    div.appendChild(avatar);
    div.appendChild(content);
    chatMessages.appendChild(div);
    if (animate) chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function downloadData(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function appendTyping() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-avatar">✦</div>
        <div class="message-content">
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function formatText(text) {
    if (typeof text !== 'string') {
        text = JSON.stringify(text, null, 2);
    }
    // Convert newlines
    text = text.replace(/\n/g, '<br>');
    // Bold **text**
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Inline code
    text = text.replace(/`(.*?)`/g, '<code style="background:rgba(80,191,247,0.1);padding:1px 5px;border-radius:3px;font-family:var(--font-mono);font-size:12px;color:var(--accent);">$1</code>');
    return text;
}

function formatSearchResult(data) {
    if (data.stars && data.stars.length > 0) {
        let html = `Found **${data.count || data.stars.length} stars**:\n\n`;
        html += '| Source ID | RA | Dec | G-mag | Distance |\n';
        html += '|---|---|---|---|---|\n';
        for (const s of data.stars.slice(0, 10)) {
            const dist = s.angular_distance ? s.angular_distance.toFixed(4) + '°' : '-';
            html += `| ${s.source_id} | ${s.ra.toFixed(4)} | ${s.dec.toFixed(4)} | ${(s.phot_g_mean_mag || '-')} | ${dist} |\n`;
        }
        return html;
    }

    if (data.source_id) {
        let info = `**Star ${data.source_id}**\n`;
        info += `• RA: ${data.ra?.toFixed(6)}°\n`;
        info += `• Dec: ${data.dec?.toFixed(6)}°\n`;
        if (data.parallax) info += `• Parallax: ${data.parallax.toFixed(4)} mas\n`;
        if (data.phot_g_mean_mag) info += `• G-mag: ${data.phot_g_mean_mag.toFixed(3)}\n`;
        return info;
    }

    return JSON.stringify(data, null, 2);
}

// Enter key to send
// Enter key to send
document.addEventListener('DOMContentLoaded', () => {
    // Remove existing listeners if any (by cloning) or just check
    const chatInput = document.getElementById('chatInput');
    if (chatInput && !chatInput.dataset.listenerAttached) {
        chatInput.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        chatInput.dataset.listenerAttached = 'true';
    }
});


// ---- Explore Tab: Cone Search ----
async function runConeSearch() {
    const ra = parseFloat(document.getElementById('searchRA').value);
    const dec = parseFloat(document.getElementById('searchDec').value);
    const radius = parseFloat(document.getElementById('searchRadius').value);
    const magLimit = document.getElementById('searchMag').value;

    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Searching...';

    try {
        let url = `${API}/api/stars/cone-search?ra=${ra}&dec=${dec}&radius=${radius}&limit=50`;
        if (magLimit) url += `&mag_limit=${magLimit}`;

        const resp = await fetch(url);
        const data = await resp.json();
        displayResults(data.stars || [], data.count);

        // Also get count
        const countResp = await fetch(`${API}/api/stars/count?ra=${ra}&dec=${dec}&radius=${radius}`);
        const countData = await countResp.json();
        document.getElementById('regionCount').textContent = countData.count?.toLocaleString() || '0';
    } catch (err) {
        alert('Search failed: ' + err.message);
    }

    btn.disabled = false;
    btn.textContent = 'Search Stars';
}

function displayResults(stars, totalCount) {
    const card = document.getElementById('resultsCard');
    const body = document.getElementById('resultsBody');
    const count = document.getElementById('resultsCount');

    if (!stars || stars.length === 0) {
        card.style.display = 'none';
        return;
    }

    card.style.display = 'block';
    count.textContent = `${stars.length} of ${totalCount || stars.length} results`;
    body.innerHTML = '';

    for (const s of stars) {
        const bpRp = (s.phot_bp_mean_mag && s.phot_rp_mean_mag)
            ? (s.phot_bp_mean_mag - s.phot_rp_mean_mag).toFixed(3)
            : '-';
        const dist = s.angular_distance ? s.angular_distance.toFixed(4) : '-';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${s.source_id}</td>
            <td>${s.ra?.toFixed(4)}</td>
            <td>${s.dec?.toFixed(4)}</td>
            <td>${s.phot_g_mean_mag?.toFixed(2) || '-'}</td>
            <td>${bpRp}</td>
            <td>${s.parallax?.toFixed(3) || '-'}</td>
            <td>${dist}</td>
            <td><button class="btn-sm" onclick="viewStar('${s.source_id}')">View</button></td>
        `;
        body.appendChild(tr);
    }
}

// ---- Explore Tab: Star Lookup ----
async function runStarLookup() {
    const sid = document.getElementById('lookupId').value.trim();
    if (!sid) return;

    const resultBox = document.getElementById('lookupResult');
    resultBox.classList.remove('hidden');
    resultBox.innerHTML = '<div class="text-slate-400 text-xs">Loading...</div>';

    try {
        const resp = await fetch(`${API}/api/stars/lookup/${sid}`);
        if (!resp.ok) {
            resultBox.innerHTML = '<div class="text-red-400 text-xs">Star not found.</div>';
            return;
        }
        const s = await resp.json();
        const bpRp = (s.phot_bp_mean_mag && s.phot_rp_mean_mag)
            ? (s.phot_bp_mean_mag - s.phot_rp_mean_mag).toFixed(3)
            : 'N/A';

        resultBox.innerHTML = `
            <div class="grid grid-cols-2 gap-y-2 text-[11px] font-mono">
                <div class="text-slate-500 dark:text-slate-400">Source ID</div>
                <div class="text-right text-slate-700 dark:text-slate-300">${s.source_id}</div>
                <div class="text-slate-500 dark:text-slate-400">RA</div>
                <div class="text-right text-slate-700 dark:text-slate-300">${s.ra?.toFixed(6)}</div>
                <div class="text-slate-500 dark:text-slate-400">Dec</div>
                <div class="text-right text-slate-700 dark:text-slate-300">${s.dec?.toFixed(6)}</div>
                <div class="text-slate-500 dark:text-slate-400">Parallax</div>
                <div class="text-right text-primary">${s.parallax?.toFixed(4) || '-'} mas</div>
                <div class="text-slate-500 dark:text-slate-400">G-mag</div>
                <div class="text-right text-slate-700 dark:text-slate-300">${s.phot_g_mean_mag?.toFixed(3)}</div>
                <div class="text-slate-500 dark:text-slate-400">BP-RP</div>
                <div class="text-right text-slate-700 dark:text-slate-300">${bpRp}</div>
            </div>
        `;
    } catch (err) {
        resultBox.innerHTML = `<div class="text-red-400 text-xs">Error: ${err.message}</div>`;
    }
}

function viewStar(sid) {
    document.getElementById('lookupId').value = sid;
    runStarLookup();
    // Scroll to the lookup card
    document.querySelector('.lookup-card')?.scrollIntoView({ behavior: 'smooth' });
}


// ---- Stats Tab ----
// ---- Stats Tab ----
async function loadStats() {
    const setStatus = (el, active, text) => {
        if (!el) return;
        el.textContent = text || (active ? 'Active' : 'Offline');
        el.className = active
            ? 'px-2 py-0.5 rounded text-[10px] font-bold bg-green-500/10 text-green-400 border border-green-500/20'
            : 'px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/10 text-red-400 border border-red-500/20';
    };

    try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        // Backend returns: { postgresql: { status: 'connected', total_stars: N }, qdrant: { status: 'green', points_count: N }, neo4j: ... }

        const pgData = data.postgresql || {};
        const qData = data.qdrant || {};

        // Q3C (Uses Postgres Data)
        const q3cEl = document.getElementById('q3cStatus');
        if (q3cEl) {
            const isActive = pgData.status === 'connected';
            setStatus(q3cEl, isActive, isActive ? 'Active' : 'Error');
            const rowEl = document.getElementById('q3cRows');
            if (rowEl) rowEl.textContent = (pgData.total_stars || 0).toLocaleString();
        }

        // Postgres
        const pgEl = document.getElementById('pgStatus');
        if (pgEl) {
            const isActive = pgData.status === 'connected';
            setStatus(pgEl, isActive, isActive ? 'Active' : 'Error');
            const pgMain = document.getElementById('pgMainStatus');
            if (pgMain) {
                pgMain.textContent = isActive ? 'Online' : 'Offline';
                pgMain.className = `text-2xl font-bold mb-1 ${isActive ? 'text-white' : 'text-red-400'}`;
            }
        }

        // Qdrant
        const qdrantEl = document.getElementById('qdrantStatus');
        if (qdrantEl) {
            // Check for green/yellow status OR valid points count
            const exists = qData.exists !== false;
            const isHealthy = qData.status === 'green' || qData.status === 'yellow';
            const isActive = exists && isHealthy;

            const statusText = isActive ? 'Ready' : (exists ? 'Error' : 'Empty');
            const statusColor = isActive ? 'green' : (exists ? 'red' : 'yellow');

            setStatus(qdrantEl, isActive, statusText);
            const qdrantMain = document.getElementById('qdrantMainStatus');
            if (qdrantMain) {
                qdrantMain.textContent = statusText;
                qdrantMain.className = `text-2xl font-bold mb-1 ${isActive ? 'text-white' : (exists ? 'text-red-400' : 'text-yellow-400')}`;
            }
        }

    } catch (e) {
        console.error("Stats error", e);
        const els = ['q3cStatus', 'pgStatus', 'qdrantStatus'];
        els.forEach(id => {
            const el = document.getElementById(id);
            if (el) setStatus(el, false, 'Error');
        });
    }
}

// ---- Theme ----
function initTheme() {
    const themeToggle = document.getElementById('themeToggle');

    // Check saved preference or system preference (default to dark)
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = savedTheme === 'dark' || (!savedTheme && prefersDark) || (!savedTheme && !prefersDark && true); // Default to dark if undefined? HTML has class="dark".
    // Actually HTML has class="dark" by default.
    // Logic: If saved 'light', remove class. Else ensure class.

    if (savedTheme === 'light') {
        document.documentElement.classList.remove('dark');
        if (themeToggle) themeToggle.checked = false;
    } else {
        document.documentElement.classList.add('dark');
        if (themeToggle) themeToggle.checked = true;
    }

    // Toggle Listener
    if (themeToggle) {
        themeToggle.addEventListener('change', () => {
            if (themeToggle.checked) {
                document.documentElement.classList.add('dark');
                localStorage.setItem('theme', 'dark');
            } else {
                document.documentElement.classList.remove('dark');
                localStorage.setItem('theme', 'light');
            }
        });
    }
}

// ---- Sidebar ----
function initSidebar() {
    const sidebar = document.getElementById('mainSidebar');
    const toggleBtn = document.getElementById('sidebarToggle');

    if (!sidebar || !toggleBtn) return;

    // Toggle Function
    function toggle() {
        const isCollapsed = sidebar.classList.toggle('sidebar-collapsed');
        sidebar.classList.toggle('w-64');
        sidebar.classList.toggle('w-20');
        localStorage.setItem('sidebarCollapsed', isCollapsed);
    }

    toggleBtn.addEventListener('click', toggle);

    // Init State
    if (localStorage.getItem('sidebarCollapsed') === 'true') {
        sidebar.classList.add('sidebar-collapsed', 'w-20');
        sidebar.classList.remove('w-64');
    }
}

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initSidebar();
    initTheme();

    // Check for query param
    const urlParams = new URLSearchParams(window.location.search);
    const q = urlParams.get('q');
    if (q) {
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.value = q;
            window.history.replaceState({}, document.title, "/");
            // Small delay to ensure UI is ready
            setTimeout(() => sendMessage(), 100);
        }
    }

    // Load Stats if on System page
    if (document.getElementById('q3cStatus')) {
        loadStats();
    }
});
