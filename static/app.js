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

const MAX_FILE_SIZE = 50 * 1024; // 50KB

function newChat() {
    if (confirm("Start a new chat? Your current conversation will be saved to History.")) {
        // 1. Archive current session if it has messages
        if (chatHistory && chatHistory.length > 0) {
            saveCurrentSessionToArchive();
            localStorage.setItem('taarya_flash_message', 'Session Saved to History');
        }

        // 2. Clear and Reload
        chatHistory = [];
        localStorage.removeItem('taarya_chat_history');
        window.location.reload();
    }
}

function saveCurrentSessionToArchive() {
    try {
        let archives = JSON.parse(localStorage.getItem('taarya_archives') || '[]');

        // title from first user message
        const firstUserMsg = chatHistory.find(m => m.role === 'user' || m.role === 'human');
        let title = firstUserMsg ? firstUserMsg.content.substring(0, 30) : 'Untitled Chat';
        if (firstUserMsg && firstUserMsg.content.length > 30) title += '...';

        const session = {
            id: Date.now(),
            timestamp: Date.now(),
            title: title,
            messages: chatHistory
        };

        // Prepend (newest first)
        archives.unshift(session);
        // Limit archives to 10
        if (archives.length > 10) archives = archives.slice(0, 10);

        localStorage.setItem('taarya_archives', JSON.stringify(archives));
    } catch (e) {
        console.error("Failed to archive session", e);
    }
}

function loadArchivedSessions() {
    const list = document.getElementById('sessionList');
    if (!list) return;

    try {
        const archives = JSON.parse(localStorage.getItem('taarya_archives') || '[]');
        if (archives.length === 0) {
            list.innerHTML = '<div class="text-[10px] text-gray-400 px-3 italic">No saved chats yet.</div>';
            return;
        }

        list.innerHTML = '';
        archives.forEach(session => {
            const btn = document.createElement('button');
            btn.className = 'w-full text-left px-3 py-2 rounded-md text-xs text-gray-700 dark:text-gray-400 hover:text-black dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 truncate transition-all flex items-center gap-2 group';
            // Format date: "Feb 10, 10:30"
            const dateStr = new Date(session.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

            btn.innerHTML = `
                <span class="material-icons text-[14px] opacity-0 group-hover:opacity-100 transition-opacity">restore</span>
                <span class="truncate flex-1">${session.title}</span>
                <span class="text-[9px] opacity-50">${dateStr}</span>
            `;
            btn.onclick = () => restoreSession(session.id);
            list.appendChild(btn);
        });
    } catch (e) {
        console.error("Error loading archives", e);
    }
}

function restoreSession(id) {
    if (chatHistory.length > 0) {
        if (confirm("Save current chat before switching?")) {
            saveCurrentSessionToArchive();
        }
    }

    const archives = JSON.parse(localStorage.getItem('taarya_archives') || '[]');
    const session = archives.find(s => s.id === id);
    if (!session) return;

    localStorage.setItem('taarya_chat_history', JSON.stringify(session.messages));
    window.location.reload();
}

function handleFileUpload(input) {
    const file = input.files[0];
    if (!file) return;

    if (file.size > MAX_FILE_SIZE) {
        alert(`File too large (${(file.size / 1024).toFixed(1)}KB). Limit is 50KB.`);
        input.value = '';
        return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
        const content = e.target.result;
        // Construct a prompt context
        const hiddenMsg = `I am uploading a file named "${file.name}". Here is the content:\n\`\`\`\n${content}\n\`\`\`\nPlease analyze this data if requested.`;

        // Show UI bubble for file
        appendMessage('user', `📁 **Uploaded File:** ${file.name} \n<span class="text-xs opacity-70">${(file.size / 1024).toFixed(1)} KB</span>`);

        // Send to agent (skip UI for user part since we just added it)
        sendMessage(hiddenMsg, true);
    };
    reader.readAsText(file);
    input.value = '';
}

async function sendMessage(overrideText = null, skipUserUI = false) {
    let text = overrideText || chatInput.value.trim();
    if (!text) return;

    if (!overrideText) chatInput.value = '';

    // Add user message if not skipped
    if (!skipUserUI) {
        appendMessage('user', text);
    }

    // Show typing indicator
    const typingEl = appendTyping();

    // Disable send button
    const sendBtn = document.getElementById('chatSend');
    if (sendBtn) sendBtn.disabled = true;

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
            // For file upload, we might want to store the "User uploaded..." text in history 
            // so context is preserved, even if UI showed "Uploaded File".
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

    if (sendBtn) sendBtn.disabled = false;
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

    // Header with Download Button
    const headerHtml = `
        <div class="flex justify-between items-center mb-4">
            <span class="text-sm font-bold text-gray-700 dark:text-gray-300">
                ${stars.length} of ${totalCount || stars.length} results
            </span>
            <button onclick='downloadData(${JSON.stringify(stars)}, "cone_search_results.json")' 
                class="flex items-center gap-2 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary rounded text-xs transition-colors border border-primary/20">
                <span class="material-icons text-[14px]">download</span>
                Export JSON
            </button>
        </div>
    `;

    // We can't easily replace just the count text node if we want a button next to it 
    // without changing HTML structure.
    // The current HTML has `<div id="resultsCount">...</div>` inside the card.
    // I'll replace the content of `resultsCount` with this header? 
    // No, `resultsCount` is a span or div?
    // Let's check index.html again or just overwrite `count.innerHTML`.

    count.innerHTML = `
        ${stars.length} / ${totalCount || stars.length} results
        <button onclick='downloadData(${JSON.stringify(stars).replace(/'/g, "&#39;")}, "cone_search_results.json")' 
            class="ml-4 inline-flex items-center gap-1 px-2 py-0.5 bg-primary/10 hover:bg-primary/20 text-primary rounded text-[10px] transition-colors border border-primary/20 align-middle">
            <span class="material-icons text-[10px]">download</span> Export
        </button>
    `;

    body.innerHTML = '';

    for (const s of stars) {
        const bpRp = (s.phot_bp_mean_mag && s.phot_rp_mean_mag)
            ? (s.phot_bp_mean_mag - s.phot_rp_mean_mag).toFixed(3)
            : '-';
        const dist = s.angular_distance ? s.angular_distance.toFixed(4) : '-';

        // Styling: Source ID like code, RA/Dec monospace, Mag highlighted if bright
        const magClass = (s.phot_g_mean_mag && s.phot_g_mean_mag < 10)
            ? 'font-bold text-yellow-500 dark:text-yellow-400'
            : 'text-gray-700 dark:text-gray-300';

        const tr = document.createElement('tr');
        tr.className = 'hover:bg-primary/5 transition-colors group'; // Hover effect
        tr.innerHTML = `
            <td class="p-3 border-b border-gray-100 dark:border-white/5">
                <span class="font-mono text-[10px] text-primary bg-primary/10 px-1.5 py-0.5 rounded select-all cursor-pointer hover:bg-primary/20 transition-colors" title="Click to copy" onclick="navigator.clipboard.writeText('${s.source_id}')">${s.source_id}</span>
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono text-gray-600 dark:text-gray-400">
                ${s.ra?.toFixed(5)}
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono text-gray-600 dark:text-gray-400">
                ${s.dec?.toFixed(5)}
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono ${magClass}">
                ${s.phot_g_mean_mag?.toFixed(3) || '-'}
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono text-gray-500 dark:text-gray-500">
                ${bpRp}
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono text-secondary">
                ${s.parallax?.toFixed(3) || '-'}
            </td>
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-right font-mono text-gray-500 dark:text-gray-400">
                ${dist}
            </td>
            
            <td class="p-3 border-b border-gray-100 dark:border-white/5 text-center">
                <button class="text-[10px] px-2 py-1 rounded border border-gray-200 dark:border-white/10 hover:bg-primary hover:text-white hover:border-primary transition-all opacity-0 group-hover:opacity-100" onclick="viewStar('${s.source_id}')">
                    Full
                </button>
            </td>
        `;

        // Removed the 'Distance' column from JS loop? 
        // Need to check explore.html table header columns!
        // It has Headers: Source ID, RA, Dec, G Mag, BP-RP, Parallax, Actions (7 cols)
        // My previous code had: dist column? Let's check diff or previous view.

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
            <div class="flex justify-between items-start mb-2 border-b border-gray-700/50 pb-2">
                <span class="text-xs font-bold text-white">Star Details</span>
                <button onclick='downloadData(${JSON.stringify(s)}, "star_${s.source_id}.json")' 
                    class="text-[10px] flex items-center gap-1 text-primary hover:text-primary-light">
                    <span class="material-icons text-[10px]">download</span> JSON
                </button>
            </div>
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

    // Load Archives
    loadArchivedSessions();

    // Check Flash Message
    const flash = localStorage.getItem('taarya_flash_message');
    if (flash) {
        localStorage.removeItem('taarya_flash_message'); // Clear
        const toast = document.createElement('div');
        toast.className = 'fixed top-4 right-4 bg-green-500 text-white px-4 py-2 rounded shadow-lg z-50 text-sm animate-bounce';
        toast.textContent = flash;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
});
