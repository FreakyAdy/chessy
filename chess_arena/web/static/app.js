/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * CHESS ARENA — FRONTEND APPLICATION JAVASCRIPT
 * Real-time WebSocket streaming, FEN board renderer, and 5-bot uploader gate.
 * ═══════════════════════════════════════════════════════════════════════════════
 */

(function () {
  'use strict';

  // ── State Variables ────────────────────────────────────────────────────────
  let socket = null;
  let isConnected = false;
  let isRunning = false;
  let isPaused = false;
  let currentMatchNumber = 1;
  let currentFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
  let availableBots = [];
  let selectedBotIds = new Set(['greedy', 'minimax_d2']);
  let soundEnabled = true;

  // Chess piece Unicode glyph mapping (identical solid shapes rendered into high-contrast tiles)
  const PIECE_SYMBOLS = {
    'p': '♟', 'n': '♞', 'b': '♝', 'r': '♜', 'q': '♛', 'k': '♚',
    'P': '♟', 'N': '♞', 'B': '♝', 'R': '♜', 'Q': '♛', 'K': '♚',
  };

  const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
  const RANKS = ['8', '7', '6', '5', '4', '3', '2', '1'];

  // ── DOM References ─────────────────────────────────────────────────────────
  const elChessboard = document.getElementById('chessboard');
  const elConnectionStatus = document.getElementById('connection-status');
  const elStatusPill = document.getElementById('status-pill');
  const elStatusPillText = document.getElementById('status-pill-text');
  const elMatchNumberBadge = document.getElementById('match-number-badge');
  const elTournamentFormatBadge = document.getElementById('tournament-format-badge');
  const elPlayerWhiteName = document.getElementById('player-white-name');
  const elPlayerBlackName = document.getElementById('player-black-name');
  const elWhiteCapturedBox = document.getElementById('white-captured-box');
  const elBlackCapturedBox = document.getElementById('black-captured-box');
  const elTurnDot = document.getElementById('turn-dot');
  const elTurnText = document.getElementById('turn-text');
  const elLastMoveText = document.getElementById('last-move-text');
  const elClockText = document.getElementById('clock-text');
  const elTimerBar = document.getElementById('timer-bar');
  const elFenText = document.getElementById('fen-text');
  const elBtnCopyFen = document.getElementById('btn-copy-fen');
  const elRefereeLegalCount = document.getElementById('referee-legal-count');
  const elRefereeHalfmoveCount = document.getElementById('referee-halfmove-count');
  const elRefereeCheckStatus = document.getElementById('referee-check-status');
  const elMoveHistoryList = document.getElementById('move-history-list');
  const elStandingsTbody = document.getElementById('standings-tbody');
  const elMatchOutcomeBanner = document.getElementById('match-outcome-banner');
  const elFooterPgnPath = document.getElementById('footer-pgn-path');

  // Control Buttons
  const elBtnStart = document.getElementById('btn-start-tourney');
  const elBtnStartText = document.getElementById('btn-start-text');
  const elBtnPause = document.getElementById('btn-pause-tourney');
  const elBtnPauseText = document.getElementById('btn-pause-text');
  const elPauseIcon = document.getElementById('pause-icon');
  const elBtnStop = document.getElementById('btn-stop-tourney');
  const elSpeedSlider = document.getElementById('speed-slider');
  const elSpeedValue = document.getElementById('speed-value');
  const elSelectFormat = document.getElementById('select-format');
  const elBtnDownloadPgn = document.getElementById('btn-download-pgn');
  const elBtnSoundToggle = document.getElementById('btn-sound-toggle');
  const elSoundIcon = document.getElementById('sound-icon');

  // Modal References
  const elBotModal = document.getElementById('bot-modal');
  const elBtnOpenBotModal = document.getElementById('btn-open-bot-modal');
  const elBtnCloseModal = document.getElementById('btn-close-modal');
  const elBtnCancelModal = document.getElementById('btn-cancel-modal');
  const elBtnApplyRoster = document.getElementById('btn-apply-roster');
  const elDropZone = document.getElementById('drop-zone');
  const elBotFileInput = document.getElementById('bot-file-input');
  const elAuditResultCard = document.getElementById('audit-result-card');
  const elAuditBotName = document.getElementById('audit-bot-name');
  const elAuditQualificationBadge = document.getElementById('audit-qualification-badge');
  const elAuditScoreNum = document.getElementById('audit-score-num');
  const elAuditLatencyAvg = document.getElementById('audit-latency-avg');
  const elAuditLatencyPeak = document.getElementById('audit-latency-peak');
  const elAuditChecksPassed = document.getElementById('audit-checks-passed');
  const elAuditFindingsList = document.getElementById('audit-findings-list');
  const elBotListContainer = document.getElementById('bot-list-container');
  const elBotCountBadge = document.getElementById('bot-count-badge');
  const elSelectedCountPill = document.getElementById('selected-count-pill');

  // ── Web Audio Synth (Pleasant Wooden Move Click) ────────────────────────────
  let audioCtx = null;
  function playMoveSound(isCapture = false) {
    if (!soundEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }

      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.connect(gain);
      gain.connect(audioCtx.destination);

      const now = audioCtx.currentTime;
      if (isCapture) {
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(220, now);
        osc.frequency.exponentialRampToValueAtTime(110, now + 0.08);
        gain.gain.setValueAtTime(0.3, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.08);
        osc.start(now);
        osc.stop(now + 0.08);
      } else {
        osc.type = 'sine';
        osc.frequency.setValueAtTime(440, now);
        osc.frequency.exponentialRampToValueAtTime(180, now + 0.05);
        gain.gain.setValueAtTime(0.2, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.05);
        osc.start(now);
        osc.stop(now + 0.05);
      }
    } catch (e) {
      // Audio context suppressed or not allowed
    }
  }

  // ── Board Initialisation & Rendering ───────────────────────────────────────
  const squaresMap = {}; // squareName -> DOM element

  function initBoard() {
    elChessboard.innerHTML = '';
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        const sqName = FILES[f] + RANKS[r];
        const isLight = (r + f) % 2 === 0;

        const sqDiv = document.createElement('div');
        sqDiv.className = `square ${isLight ? 'light' : 'dark'}`;
        sqDiv.dataset.square = sqName;

        elChessboard.appendChild(sqDiv);
        squaresMap[sqName] = sqDiv;
      }
    }
    renderFen(currentFen);
  }

  function renderFen(fen, fromSq = null, toSq = null) {
    if (!fen) return;
    currentFen = fen;
    elFenText.textContent = fen;

    // Clear previous pieces and highlights
    for (const sqName in squaresMap) {
      const sq = squaresMap[sqName];
      sq.innerHTML = '';
      sq.classList.remove('highlight-from', 'highlight-to', 'in-check');
    }

    if (fromSq && squaresMap[fromSq]) {
      squaresMap[fromSq].classList.add('highlight-from');
    }
    if (toSq && squaresMap[toSq]) {
      squaresMap[toSq].classList.add('highlight-to');
    }

    // Parse FEN piece placement
    const [placement, turn] = fen.split(' ');
    const ranks = placement.split('/');

    for (let r = 0; r < 8; r++) {
      const rankStr = ranks[r];
      let f = 0;
      for (let i = 0; i < rankStr.length; i++) {
        const char = rankStr[i];
        if (char >= '1' && char <= '8') {
          f += parseInt(char, 10);
        } else {
          const sqName = FILES[f] + RANKS[r];
          const isWhite = char === char.toUpperCase();
          const symbol = PIECE_SYMBOLS[char] || char;

          const pieceTile = document.createElement('div');
          pieceTile.className = `piece-tile ${isWhite ? 'white-piece' : 'black-piece'}`;
          pieceTile.textContent = symbol;
          pieceTile.title = `${isWhite ? 'White' : 'Black'} ${char.toUpperCase()} on ${sqName}`;

          if (squaresMap[sqName]) {
            squaresMap[sqName].appendChild(pieceTile);
          }
          f++;
        }
      }
    }
  }

  function renderCapturedPieces(boxEl, capturedList, isWhiteGraveyard) {
    if (!boxEl) return;
    boxEl.innerHTML = '';
    capturedList.forEach(symbol => {
      const span = document.createElement('span');
      span.textContent = PIECE_SYMBOLS[symbol] || symbol;
      span.style.color = isWhiteGraveyard ? '#f5f5f4' : '#1c1917';
      span.style.textShadow = isWhiteGraveyard ? '0 1px 2px rgba(0,0,0,0.8)' : '0 1px 2px rgba(255,255,255,0.4)';
      boxEl.appendChild(span);
    });
  }

  // ── WebSocket Client ───────────────────────────────────────────────────────
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      isConnected = true;
      elConnectionStatus.textContent = '● Connected';
      elConnectionStatus.className = 'connection-badge connected';
    };

    socket.onclose = () => {
      isConnected = false;
      elConnectionStatus.textContent = '● Disconnected';
      elConnectionStatus.className = 'connection-badge disconnected';
      // Auto-reconnect after 2 seconds
      setTimeout(connectWebSocket, 2000);
    };

    socket.onerror = (err) => {
      console.warn('WebSocket error:', err);
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWebSocketMessage(msg);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };
  }

  function handleWebSocketMessage(msg) {
    const { type, data } = msg;

    switch (type) {
      case 'state_snapshot':
        applyStateSnapshot(data);
        break;

      case 'tournament_start':
        isRunning = true;
        isPaused = false;
        updateToolbarState();
        setStatusPill('LIVE', 'status-live');
        elMatchOutcomeBanner.classList.add('hidden');
        break;

      case 'match_start':
        currentMatchNumber = data.match_number;
        elMatchNumberBadge.textContent = `Match ${data.match_number}/${data.total_matches}`;
        elPlayerWhiteName.textContent = data.white;
        elPlayerBlackName.textContent = data.black;
        elFooterPgnPath.textContent = `pgn: games/game_${String(data.match_number).padStart(4, '0')}.pgn`;
        elBtnDownloadPgn.disabled = false;
        elMoveHistoryList.innerHTML = '';
        renderFen(data.fen);
        break;

      case 'move':
        handleMoveEvent(data);
        break;

      case 'match_end':
        handleMatchEndEvent(data);
        break;

      case 'standings':
        renderStandingsTable(data.standings);
        break;

      case 'tournament_end':
        isRunning = false;
        isPaused = false;
        updateToolbarState();
        setStatusPill('COMPLETED', 'status-completed');
        showTournamentCelebration(data.champion, data.final_standings);
        break;

      case 'tournament_stopped':
        isRunning = false;
        isPaused = false;
        updateToolbarState();
        setStatusPill('STOPPED', 'status-paused');
        break;
    }
  }

  function applyStateSnapshot(snap) {
    isRunning = snap.is_running;
    isPaused = snap.is_paused;
    currentMatchNumber = snap.current_match || 1;

    updateToolbarState();
    elSpeedSlider.value = snap.move_delay || 0.25;
    elSpeedValue.textContent = `${snap.move_delay || 0.25}s`;

    if (snap.white) elPlayerWhiteName.textContent = snap.white;
    if (snap.black) elPlayerBlackName.textContent = snap.black;
    if (snap.current_match && snap.total_matches) {
      elMatchNumberBadge.textContent = `Match ${snap.current_match}/${snap.total_matches}`;
    }

    if (snap.fen) {
      renderFen(snap.fen);
    }

    if (snap.standings && snap.standings.length > 0) {
      renderStandingsTable(snap.standings);
    }

    if (isRunning) {
      setStatusPill(isPaused ? 'PAUSED' : 'LIVE', isPaused ? 'status-paused' : 'status-live');
    } else {
      setStatusPill('READY', 'status-paused');
    }
  }

  function handleMoveEvent(d) {
    renderFen(d.fen, d.from, d.to);

    // Active turn update
    const isWhiteTurn = d.next_turn === 'white';
    elTurnDot.className = `turn-dot ${isWhiteTurn ? 'white-turn' : 'black-turn'}`;
    elTurnText.textContent = `${isWhiteTurn ? 'White' : 'Black'} to move (${isWhiteTurn ? elPlayerWhiteName.textContent : elPlayerBlackName.textContent})`;

    // Move metric badge
    elLastMoveText.textContent = `${d.move_number}. ${d.turn === 'black' ? '... ' : ''}${d.san}`;

    // Clock
    elClockText.textContent = `${d.elapsed_s.toFixed(2)}s`;
    const pct = Math.min(100, (d.elapsed_s / d.time_limit) * 100);
    elTimerBar.style.width = `${Math.max(2, pct)}%`;

    // Referee stats
    elRefereeLegalCount.textContent = d.legal_moves_count;
    elRefereeHalfmoveCount.textContent = d.halfmove_clock;
    elRefereeCheckStatus.textContent = d.is_check ? 'TRUE (In Check!)' : 'False';
    if (d.is_check) {
      elRefereeCheckStatus.style.color = 'var(--accent-red)';
    } else {
      elRefereeCheckStatus.style.color = 'var(--text-white)';
    }

    // Material capture graveyard
    if (d.white_captured) renderCapturedPieces(elWhiteCapturedBox, d.white_captured, true);
    if (d.black_captured) renderCapturedPieces(elBlackCapturedBox, d.black_captured, false);

    // Append to Move Stream
    appendMoveLog(d.move_number, d.turn, d.san, d.elapsed_s);

    // Play subtle audio sound
    playMoveSound(d.san.includes('x'));
  }

  function appendMoveLog(moveNum, turn, san, elapsed) {
    let row = elMoveHistoryList.querySelector(`.move-row-${moveNum}`);
    if (!row) {
      row = document.createElement('div');
      row.className = `history-row move-row-${moveNum}`;
      elMoveHistoryList.appendChild(row);
    }

    const moveSpan = document.createElement('span');
    moveSpan.innerHTML = `<strong>${turn === 'white' ? moveNum + '.' : '...'}</strong> ${san} <span style="color: var(--text-dim); font-size: 10px;">(${elapsed.toFixed(2)}s)</span>`;
    row.appendChild(moveSpan);

    // Auto-scroll to bottom
    elMoveHistoryList.scrollTop = elMoveHistoryList.scrollHeight;
  }

  function handleMatchEndEvent(d) {
    const res = d.result;
    elMatchOutcomeBanner.classList.remove('hidden');
    elMatchOutcomeBanner.textContent = `Match ${d.match_number} Result: ${res.outcome} • ${res.reason}`;

    if (res.outcome === '1-0') {
      elMatchOutcomeBanner.style.borderColor = 'var(--accent-green)';
    } else if (res.outcome === '0-1') {
      elMatchOutcomeBanner.style.borderColor = 'var(--accent-purple)';
    } else {
      elMatchOutcomeBanner.style.borderColor = 'var(--accent-blue)';
    }
  }

  function renderStandingsTable(standings) {
    if (!standings || standings.length === 0) return;
    elStandingsTbody.innerHTML = '';

    standings.forEach((s, idx) => {
      const tr = document.createElement('tr');
      const winRate = s.games_played > 0 ? ((s.wins / s.games_played) * 100).toFixed(1) : '0.0';

      tr.innerHTML = `
        <td class="col-rank font-mono">${idx + 1}</td>
        <td class="col-bot"><strong>${s.name}</strong></td>
        <td class="col-pts font-mono font-bold">${s.points.toFixed(1)}</td>
        <td class="col-stat font-mono">${s.wins}</td>
        <td class="col-stat font-mono">${s.draws}</td>
        <td class="col-stat font-mono">${s.losses}</td>
        <td class="col-stat font-mono">${s.games_played}</td>
        <td class="col-rate font-mono">${winRate}%</td>
      `;
      elStandingsTbody.appendChild(tr);
    });
  }

  function showTournamentCelebration(champion, finalStandings) {
    elMatchOutcomeBanner.classList.remove('hidden');
    elMatchOutcomeBanner.innerHTML = `🎉 <strong>TOURNAMENT FINISHED!</strong> Champion: <span style="color: var(--accent-green);">${champion}</span> 🏆`;
    renderStandingsTable(finalStandings);
  }

  function setStatusPill(text, className) {
    elStatusPill.className = `status-pill ${className}`;
    elStatusPillText.textContent = text;
  }

  function updateToolbarState() {
    elBtnStart.disabled = isRunning;
    elBtnPause.disabled = !isRunning;
    elBtnStop.disabled = !isRunning;

    if (isPaused) {
      elPauseIcon.textContent = '▶';
      elBtnPauseText.textContent = 'Resume';
    } else {
      elPauseIcon.textContent = '⏸';
      elBtnPauseText.textContent = 'Pause';
    }
  }

  // ── Tournament REST Controls ───────────────────────────────────────────────
  async function startTournament() {
    if (selectedBotIds.size < 2) {
      alert('Please select at least 2 bots in the Bot Manager.');
      openBotModal();
      return;
    }

    try {
      elBtnStart.disabled = true;
      elBtnStartText.textContent = 'Launching...';

      const resp = await fetch('/api/tournament/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bot_ids: Array.from(selectedBotIds),
          format: elSelectFormat.value,
          games_per_pair: 2,
          time_limit: 5.0,
          move_delay: parseFloat(elSpeedSlider.value),
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        alert(`Could not start tournament: ${err.detail || 'Unknown error'}`);
        elBtnStart.disabled = false;
        elBtnStartText.textContent = 'Start Tournament';
      }
    } catch (e) {
      console.error('Failed to start tournament:', e);
      elBtnStart.disabled = false;
      elBtnStartText.textContent = 'Start Tournament';
    }
  }

  async function togglePause() {
    try {
      if (isPaused) {
        await fetch('/api/tournament/resume', { method: 'POST' });
        isPaused = false;
        setStatusPill('LIVE', 'status-live');
      } else {
        await fetch('/api/tournament/pause', { method: 'POST' });
        isPaused = true;
        setStatusPill('PAUSED', 'status-paused');
      }
      updateToolbarState();
    } catch (e) {
      console.error('Pause/resume failed:', e);
    }
  }

  async function stopTournament() {
    if (!confirm('Are you sure you want to stop the tournament?')) return;
    try {
      await fetch('/api/tournament/stop', { method: 'POST' });
    } catch (e) {
      console.error('Failed to stop tournament:', e);
    }
  }

  async function updateSpeed() {
    const delay = parseFloat(elSpeedSlider.value);
    elSpeedValue.textContent = `${delay.toFixed(2)}s`;
    try {
      await fetch('/api/tournament/speed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delay }),
      });
    } catch (e) {
      console.error('Failed to update speed:', e);
    }
  }

  function downloadCurrentPgn() {
    window.location.href = `/api/pgn/${currentMatchNumber}`;
  }

  function copyCurrentFen() {
    navigator.clipboard.writeText(currentFen).then(() => {
      elBtnCopyFen.textContent = 'Copied!';
      setTimeout(() => {
        elBtnCopyFen.textContent = 'Copy';
      }, 1500);
    });
  }

  // ── Bot Manager & Uploader Modal ───────────────────────────────────────────
  function openBotModal() {
    elBotModal.classList.remove('hidden');
    loadBots();
  }

  function closeBotModal() {
    elBotModal.classList.add('hidden');
  }

  async function loadBots() {
    try {
      const resp = await fetch('/api/bots');
      const data = await resp.json();
      availableBots = data.bots;
      elBotCountBadge.textContent = availableBots.length;
      renderBotSelectorList();
    } catch (e) {
      console.error('Failed to load bots:', e);
    }
  }

  function renderBotSelectorList() {
    elBotListContainer.innerHTML = '';
    elSelectedCountPill.textContent = `${selectedBotIds.size} / 5 Selected`;

    availableBots.forEach(bot => {
      const isSelected = selectedBotIds.has(bot.id);
      const card = document.createElement('div');
      card.className = `bot-select-card ${isSelected ? 'selected' : ''}`;

      const badgeType = bot.is_uploaded ? 'badge-community' : (bot.type === 'search' ? 'badge-search' : 'badge-heuristic');

      card.innerHTML = `
        <input type="checkbox" id="chk-${bot.id}" value="${bot.id}" ${isSelected ? 'checked' : ''} ${!bot.is_eligible ? 'disabled' : ''}>
        <div class="bot-card-info">
          <div class="bot-card-name">
            <span class="bot-title-text">${bot.name}</span>
            <span class="badge ${badgeType}">${bot.type}</span>
            ${bot.is_eligible ? '<span class="badge badge-eligible">Eligible</span>' : '<span class="badge badge-disqualified">Disqualified</span>'}
            ${bot.is_uploaded ? `<button class="btn-delete-bot" title="Delete custom bot" data-id="${bot.id}">🗑 Delete</button>` : ''}
          </div>
          <div class="bot-card-desc">${bot.description}</div>
        </div>
      `;

      card.addEventListener('click', (e) => {
        if (e.target.closest('.btn-delete-bot')) return;
        if (e.target.tagName !== 'INPUT' && bot.is_eligible) {
          const chk = card.querySelector('input[type="checkbox"]');
          chk.checked = !chk.checked;
          chk.dispatchEvent(new Event('change'));
        }
      });

      const delBtn = card.querySelector('.btn-delete-bot');
      if (delBtn) {
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          if (!confirm(`Are you sure you want to permanently delete custom bot "${bot.name}"?`)) return;
          try {
            delBtn.disabled = true;
            delBtn.textContent = '...';
            const resp = await fetch(`/api/bots/${encodeURIComponent(bot.id)}`, { method: 'DELETE' });
            if (!resp.ok) {
              const err = await resp.json();
              alert(`Could not delete bot: ${err.detail || 'Unknown error'}`);
              delBtn.disabled = false;
              delBtn.textContent = '🗑 Delete';
              return;
            }
            selectedBotIds.delete(bot.id);
            await loadBots();
          } catch (err) {
            console.error('Delete bot failed:', err);
            alert('Failed to delete bot.');
          }
        });
      }

      const chk = card.querySelector('input[type="checkbox"]');
      chk.addEventListener('change', (e) => {
        if (e.target.checked) {
          if (selectedBotIds.size >= 5) {
            alert('You can select a maximum of 5 bots for the tournament.');
            e.target.checked = false;
            return;
          }
          selectedBotIds.add(bot.id);
          card.classList.add('selected');
        } else {
          selectedBotIds.delete(bot.id);
          card.classList.remove('selected');
        }
        elSelectedCountPill.textContent = `${selectedBotIds.size} / 5 Selected`;
      });

      elBotListContainer.appendChild(card);
    });
  }

  // File Drag & Drop Uploader
  function setupDragAndDrop() {
    elDropZone.addEventListener('click', () => elBotFileInput.click());

    elBotFileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        uploadBotFile(e.target.files[0]);
      }
    });

    elDropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      elDropZone.classList.add('drag-over');
    });

    elDropZone.addEventListener('dragleave', () => {
      elDropZone.classList.remove('drag-over');
    });

    elDropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      elDropZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) {
        uploadBotFile(e.dataTransfer.files[0]);
      }
    });
  }

  async function uploadBotFile(file) {
    if (!file.name.endsWith('.py')) {
      alert('Only .py Python agent files can be uploaded.');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    elAuditResultCard.classList.remove('hidden');
    elAuditBotName.textContent = `Auditing ${file.name}...`;
    elAuditQualificationBadge.textContent = 'TESTING 16 FENs...';
    elAuditQualificationBadge.className = 'badge badge-baseline';
    elAuditScoreNum.textContent = '--/100';

    try {
      const resp = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      const res = await resp.json();
      if (!resp.ok) {
        alert(res.detail || 'Upload failed');
        elAuditResultCard.classList.add('hidden');
        return;
      }

      // Display Audit Results
      elAuditBotName.textContent = res.bot.name;
      elAuditScoreNum.textContent = `${res.score}/100`;
      elAuditChecksPassed.textContent = `${res.passed_checks} / ${res.total_checks}`;
      elAuditLatencyAvg.textContent = `${res.latency.avg_ms} ms`;
      elAuditLatencyPeak.textContent = `${res.latency.max_ms} ms`;

      if (res.is_eligible) {
        elAuditQualificationBadge.textContent = 'ELIGIBLE FOR TOURNAMENT';
        elAuditQualificationBadge.className = 'badge badge-eligible';
        elAuditFindingsList.innerHTML = '<div style="color: var(--accent-green);">✅ 0 Deficiencies Found: Agent is 100% compliant with FIDE & Framework rules!</div>';
        selectedBotIds.add(res.bot.id);
      } else {
        elAuditQualificationBadge.textContent = 'DISQUALIFIED';
        elAuditQualificationBadge.className = 'badge badge-disqualified';
        elAuditFindingsList.innerHTML = res.critical_findings.map(f => `<div class="finding-item">⚠️ ${f}</div>`).join('');
      }

      // Reload bots list
      await loadBots();

    } catch (e) {
      console.error('Upload failed:', e);
      alert('Upload failed. See console for details.');
      elAuditResultCard.classList.add('hidden');
    }
  }

  // ── Event Bindings ─────────────────────────────────────────────────────────
  function initEventListeners() {
    elBtnStart.addEventListener('click', startTournament);
    elBtnPause.addEventListener('click', togglePause);
    elBtnStop.addEventListener('click', stopTournament);
    elSpeedSlider.addEventListener('input', updateSpeed);
    elBtnDownloadPgn.addEventListener('click', downloadCurrentPgn);
    elBtnCopyFen.addEventListener('click', copyCurrentFen);

    elBtnOpenBotModal.addEventListener('click', openBotModal);
    elBtnCloseModal.addEventListener('click', closeBotModal);
    elBtnCancelModal.addEventListener('click', closeBotModal);
    elBtnApplyRoster.addEventListener('click', closeBotModal);

    elBtnSoundToggle.addEventListener('click', () => {
      soundEnabled = !soundEnabled;
      elSoundIcon.textContent = soundEnabled ? '🔊' : '🔇';
    });

    setupDragAndDrop();
  }

  // ── Application Bootstrap ──────────────────────────────────────────────────
  function bootstrap() {
    initBoard();
    initEventListeners();
    connectWebSocket();
    loadBots();
  }

  window.addEventListener('DOMContentLoaded', bootstrap);
})();
