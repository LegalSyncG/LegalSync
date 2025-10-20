    import { API } from '../shared/api.js';
    import { Auth } from '../shared/auth.js';

    
    document.getElementById('logoutBtn').addEventListener('click', () => Auth.logout());
    const addCaseBtn = document.getElementById('addCaseBtn');
    const addCaseModal = document.getElementById('addCaseModal');
    const closeAddCase = document.getElementById('closeAddCase');
    const submitAddCase = document.getElementById('submitAddCase');
    const caseNameEl = document.getElementById('caseName');
    const caseAudioEl = document.getElementById('caseAudio');
    const caseTranscriptFileEl = document.getElementById('caseTranscriptFile');
    const caseTranscriptTextEl = document.getElementById('caseTranscriptText');
    const pickAudioBtn = document.getElementById('pickAudio');
    const pickTranscriptBtn = document.getElementById('pickTranscript');
    const audioFileName = document.getElementById('audioFileName');
    const transcriptFileName = document.getElementById('transcriptFileName');
    const deleteCaseModal = document.getElementById('deleteCaseModal');
    const closeDeleteCase = document.getElementById('closeDeleteCase');
    const confirmDeleteCase = document.getElementById('confirmDeleteCase');
    const renameCaseModal = document.getElementById('renameCaseModal');
    const closeRenameCase = document.getElementById('closeRenameCase');
    const saveRenameCase = document.getElementById('saveRenameCase');
    const renameCaseInput = document.getElementById('renameCaseInput');
    let pendingDeleteCaseId = null;
    let pendingRenameCaseId = null;
    const caseNameById = new Map();
    const PROGRESS_STORAGE_KEY = 'ls_case_progress';
    const READY_STORAGE_KEY = 'ls_case_ready_map';
    const READY_SEEN_SESSION_KEY = 'ls_ready_seen_map';
    const audioPlayBtn = document.getElementById('audioPlayPause');
    const audioSpeedSelect = document.getElementById('audioSpeed');
    const audioSeekEl = document.getElementById('audioSeek');
    const audioCurrentTimeEl = document.getElementById('audioCurrentTime');
    const audioDurationEl = document.getElementById('audioDuration');

    function readJSON(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw);
      } catch (_) {
        return fallback;
      }
    }

    function writeJSON(key, value) {
      try {
        localStorage.setItem(key, JSON.stringify(value));
      } catch (_) {}
    }

    function readSessionJSON(key, fallback) {
      try {
        const raw = sessionStorage.getItem(key);
        if (!raw) return fallback;
        return JSON.parse(raw);
      } catch (_) {
        return fallback;
      }
    }

    function writeSessionJSON(key, value) {
      try {
        sessionStorage.setItem(key, JSON.stringify(value));
      } catch (_) {}
    }

    let progressCache = readJSON(PROGRESS_STORAGE_KEY, {});
    let readySeen = readSessionJSON(READY_SEEN_SESSION_KEY, {});
    let activeAudioNode = null;
    let isAudioScrubbing = false;
    let audioUiRaf = null;
    let audioUiInterval = null;

    function getActiveAudio() {
      if (activeAudioNode && document.body.contains(activeAudioNode)) {
        return activeAudioNode;
      }
      activeAudioNode = document.getElementById('transcriptAudio');
      return activeAudioNode;
    }

    function getAudioCurrentTime(audio) {
      const node = audio || getActiveAudio();
      return node ? node.currentTime || 0 : 0;
    }

    function setAudioCurrentTime(time) {
      const node = getActiveAudio();
      if (!node) return;
      const duration = Number.isFinite(node.duration) && node.duration > 0 ? node.duration : null;
      const target = Number(time) || 0;
      const clamped = duration != null ? Math.min(duration, Math.max(0, target)) : Math.max(0, target);
      try { node.currentTime = clamped; } catch (_) {}
      updateAudioUI(node);
    }

    function applyAudioSpeed(audio) {
      const node = audio || getActiveAudio();
      if (!node) return;
      if (!audioSpeedSelect) return;
      const rate = parseFloat(audioSpeedSelect.value || '1');
      node.playbackRate = Number.isFinite(rate) && rate > 0 ? rate : 1;
      updateAudioUI(node);
    }

    function formatTime(seconds) {
      if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
      const total = Math.floor(seconds);
      const mins = Math.floor(total / 60);
      const secs = total % 60;
      return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    function applySeekVisual(value, duration) {
      if (!audioSeekEl) return;
      const max = Number.isFinite(duration) && duration > 0 ? duration : 0;
      const val = Number.isFinite(value) ? value : 0;
      const pct = max > 0 ? Math.min(100, Math.max(0, (val / max) * 100)) : 0;
      audioSeekEl.style.background = `linear-gradient(90deg, rgba(36, 58, 115, 0.7) ${pct}%, rgba(75, 95, 178, 0.25) ${pct}%)`;
    }

    function updateAudioUI(audio) {
      const node = audio || getActiveAudio();
      if (!node) return;
      const duration = Number.isFinite(node.duration) && node.duration > 0 ? node.duration : 0;
      const current = Number.isFinite(node.currentTime) ? node.currentTime : 0;

      if (audioDurationEl) {
        audioDurationEl.textContent = formatTime(duration);
      }
      if (audioCurrentTimeEl) {
        audioCurrentTimeEl.textContent = formatTime(current);
      }
      if (audioSeekEl) {
        if (duration > 0) {
          audioSeekEl.disabled = false;
          audioSeekEl.max = duration.toString();
          if (!isAudioScrubbing) {
            const clamped = Math.min(duration, current);
            audioSeekEl.value = clamped.toString();
            if ('valueAsNumber' in audioSeekEl) {
              audioSeekEl.valueAsNumber = clamped;
            }
            applySeekVisual(clamped, duration);
          } else {
            applySeekVisual(parseFloat(audioSeekEl.value), duration);
          }
        } else {
          audioSeekEl.disabled = true;
          audioSeekEl.max = '0';
          audioSeekEl.value = '0';
          if ('valueAsNumber' in audioSeekEl) {
            audioSeekEl.valueAsNumber = 0;
          }
          applySeekVisual(0, 0);
        }
      }
      if (audioPlayBtn) {
        const paused = node.paused;
        audioPlayBtn.textContent = paused ? 'Play' : 'Pause';
        audioPlayBtn.setAttribute('aria-label', paused ? 'Play transcript audio' : 'Pause transcript audio');
      }
    }

    const requestUiFrame = (typeof window !== 'undefined' && window.requestAnimationFrame)
      ? (cb) => window.requestAnimationFrame(cb)
      : (cb) => setTimeout(cb, 16);
    const cancelUiFrame = (typeof window !== 'undefined' && window.cancelAnimationFrame)
      ? (handle) => window.cancelAnimationFrame(handle)
      : (handle) => clearTimeout(handle);

    function stopAudioTicker() {
      if (audioUiRaf != null) {
        cancelUiFrame(audioUiRaf);
        audioUiRaf = null;
      }
      if (audioUiInterval != null) {
        clearInterval(audioUiInterval);
        audioUiInterval = null;
      }
    }

    function startAudioTicker(node) {
      if (!node) return;
      stopAudioTicker();
      const tick = () => updateAudioUI(node);
      const step = () => {
        tick();
        audioUiRaf = requestUiFrame(step);
      };
      tick();
      audioUiRaf = requestUiFrame(step);
      audioUiInterval = setInterval(() => {
        if (node.paused && !node.seeking) {
          return;
        }
        tick();
      }, 200);
    }

    function setupAudioControls(audio) {
      const node = audio || getActiveAudio();
      if (!node) return;
      activeAudioNode = node;
      applyAudioSpeed(node);
      updateAudioUI(node);

      if (audioSpeedSelect) {
        audioSpeedSelect.onchange = () => {
          applyAudioSpeed(node);
        };
      }

      if (!node.dataset.lsBound) {
        node.addEventListener('loadedmetadata', () => updateAudioUI(node));
        node.addEventListener('timeupdate', () => {
          if (!isAudioScrubbing) updateAudioUI(node);
        });
        node.addEventListener('play', () => {
          startAudioTicker(node);
          updateAudioUI(node);
        });
        node.addEventListener('pause', () => {
          stopAudioTicker();
          updateAudioUI(node);
        });
        node.addEventListener('ended', () => {
          stopAudioTicker();
          updateAudioUI(node);
          if (audioSeekEl) {
            const maxVal = Number.parseFloat(audioSeekEl.max) || node.duration || 0;
            const finalVal = Number.isFinite(maxVal) ? maxVal : node.currentTime || 0;
            audioSeekEl.value = finalVal.toString();
            if ('valueAsNumber' in audioSeekEl) {
              audioSeekEl.valueAsNumber = finalVal;
            }
            applySeekVisual(finalVal, maxVal || finalVal);
          }
        });
        node.addEventListener('durationchange', () => updateAudioUI(node));
        node.addEventListener('seeking', () => updateAudioUI(node));
        node.dataset.lsBound = '1';
      }

      if (audioPlayBtn && !audioPlayBtn.dataset.lsBound) {
        audioPlayBtn.addEventListener('click', () => {
          const media = getActiveAudio();
          if (!media) return;
          if (media.paused) {
            media.play().catch(() => {});
          } else {
            media.pause();
          }
          updateAudioUI(media);
        });
        audioPlayBtn.dataset.lsBound = '1';
      }

      if (audioSeekEl && !audioSeekEl.dataset.lsBound) {
        const endScrub = (value) => {
          if (!Number.isFinite(value)) return;
          isAudioScrubbing = false;
          setAudioCurrentTime(value);
          const nodeNow = getActiveAudio();
          if (nodeNow && !nodeNow.paused && !nodeNow.ended) {
            startAudioTicker(nodeNow);
          }
        };
        const startScrub = () => { isAudioScrubbing = true; stopAudioTicker(); };
        const pointerSupport = typeof window !== 'undefined' && 'PointerEvent' in window;
        if (pointerSupport) {
          audioSeekEl.addEventListener('pointerdown', startScrub);
          audioSeekEl.addEventListener('pointerup', (e) => endScrub(parseFloat(e.target.value)));
          audioSeekEl.addEventListener('pointerleave', (e) => {
            if (isAudioScrubbing) endScrub(parseFloat(e.target.value));
          });
          audioSeekEl.addEventListener('pointercancel', (e) => {
            if (isAudioScrubbing) endScrub(parseFloat(e.target.value));
          });
        } else {
          audioSeekEl.addEventListener('mousedown', startScrub);
          audioSeekEl.addEventListener('mouseup', (e) => endScrub(parseFloat(e.target.value)));
          audioSeekEl.addEventListener('mouseleave', (e) => {
            if (isAudioScrubbing) endScrub(parseFloat(e.target.value));
          });
          audioSeekEl.addEventListener('touchstart', startScrub, { passive: true });
          audioSeekEl.addEventListener('touchend', (e) => endScrub(parseFloat(e.target.value)));
          audioSeekEl.addEventListener('touchcancel', (e) => {
            if (isAudioScrubbing) endScrub(parseFloat(e.target.value));
          });
        }
        audioSeekEl.addEventListener('change', (e) => endScrub(parseFloat(e.target.value)));
        audioSeekEl.addEventListener('input', (e) => {
          const val = parseFloat(e.target.value);
          if (Number.isFinite(val) && audioCurrentTimeEl) {
            audioCurrentTimeEl.textContent = formatTime(val);
          }
          if ('valueAsNumber' in audioSeekEl && Number.isFinite(val)) {
            audioSeekEl.valueAsNumber = val;
          }
          applySeekVisual(val, Number.parseFloat(audioSeekEl.max) || 0);
        });
        audioSeekEl.disabled = true;
        audioSeekEl.value = '0';
        if ('valueAsNumber' in audioSeekEl) {
          audioSeekEl.valueAsNumber = 0;
        }
        audioSeekEl.dataset.lsBound = '1';
      }

      if (!node.paused && !node.ended) {
        startAudioTicker(node);
      }
    }

    function persistCaseProgress(caseId, payload) {
      if (!caseId) return;
      const key = String(caseId);
      progressCache[key] = payload;
      writeJSON(PROGRESS_STORAGE_KEY, progressCache);
    }

    function getCaseProgress(caseId) {
      if (!caseId) return undefined;
      return progressCache[String(caseId)];
    }

    function removeCaseProgress(caseId) {
      if (!caseId) return;
      const key = String(caseId);
      if (progressCache[key]) {
        delete progressCache[key];
        writeJSON(PROGRESS_STORAGE_KEY, progressCache);
      }
    }

    if (addCaseBtn) {
      addCaseBtn.addEventListener('click', () => {
        addCaseModal.style.display = 'flex';
      });
    }
    if (closeAddCase) {
      closeAddCase.addEventListener('click', () => {
        addCaseModal.style.display = 'none';
      });
    }
    if (addCaseModal) {
      addCaseModal.addEventListener('click', (e) => {
        if (e.target === addCaseModal) addCaseModal.style.display = 'none';
      });
    }
    if (deleteCaseModal) {
      deleteCaseModal.addEventListener('click', (e) => {
        if (e.target === deleteCaseModal) deleteCaseModal.style.display = 'none';
      });
    }
    if (closeDeleteCase) {
      closeDeleteCase.addEventListener('click', () => { deleteCaseModal.style.display = 'none'; });
    }
    if (confirmDeleteCase) {
      confirmDeleteCase.addEventListener('click', async () => {
        try {
          if (!pendingDeleteCaseId) return;
          const deletingId = pendingDeleteCaseId;
          await API.deleteCase(deletingId);
          removeCaseProgress(deletingId);
          const readyMap = readJSON(READY_STORAGE_KEY, {});
          if (readyMap && readyMap[String(deletingId)]) {
            delete readyMap[String(deletingId)];
            writeJSON(READY_STORAGE_KEY, readyMap);
          }
          deleteCaseModal.style.display = 'none';
          pendingDeleteCaseId = null;
          // reload list after delete
          sessionStorage.setItem('ls_toast_success', 'Case deleted');
          window.location.reload();
        } catch (e) {
          showNotification('Failed to delete case', 'error');
        }
      });
    }

    if (renameCaseModal) {
      renameCaseModal.addEventListener('click', (e) => { if (e.target === renameCaseModal) renameCaseModal.style.display='none';});
    }
    if (closeRenameCase) {
      closeRenameCase.addEventListener('click', ()=>{ renameCaseModal.style.display='none'; });
    }
    if (saveRenameCase) {
      saveRenameCase.addEventListener('click', async ()=>{
        const name = (renameCaseInput && renameCaseInput.value || '').trim().slice(0,70);
        if (!name) { showNotification('Name is required', 'error'); return; }
        try {
          await API.renameCase(pendingRenameCaseId, name);
          renameCaseModal.style.display='none';
          sessionStorage.setItem('ls_toast_success', 'Case renamed');
          window.location.reload();
        } catch (e) {
          showNotification('Failed to rename case', 'error');
        }
      });
    }

    if (pickAudioBtn && caseAudioEl) {
      pickAudioBtn.addEventListener('click', () => caseAudioEl.click());
      caseAudioEl.addEventListener('change', () => {
        if (audioFileName) audioFileName.textContent = caseAudioEl.files && caseAudioEl.files[0] ? caseAudioEl.files[0].name : 'No file chosen';
      });
    }
    if (pickTranscriptBtn && caseTranscriptFileEl) {
      pickTranscriptBtn.addEventListener('click', () => caseTranscriptFileEl.click());
      caseTranscriptFileEl.addEventListener('change', () => {
        const file = caseTranscriptFileEl.files && caseTranscriptFileEl.files[0];
        if (file && !isSupportedTranscriptFile(file)) {
          showNotification('Unsupported transcript file. Please choose a TXT, DOCX, or Pages document.', 'error');
          caseTranscriptFileEl.value = '';
          if (transcriptFileName) transcriptFileName.textContent = 'No file chosen';
          return;
        }
        if (transcriptFileName) {
          transcriptFileName.textContent = file ? file.name : 'No file chosen';
        }
      });
    }
    // delete handlers configured later with notifications
    
    
    let old_start = 0;
    let old_end = 0;
    let highlightedParagraphIndex = null;
    let activeCaseId = null;
    let __entriesForActiveCase = null; // dashboard-only: transcript entries JSON for mapping/saving flags

    function resetProgressUI() {
      const wrap = document.getElementById('alignStatus');
      const bar = document.getElementById('alignProgress');
      const label = document.getElementById('alignLabel');
      if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
      progressWidth = 0;
      currentStage = null;
      if (bar) {
        bar.style.width = '0%';
        bar.classList.remove('active','failed','ready');
      }
      if (label) label.textContent = 'Waiting…';
      if (wrap) wrap.style.display = 'none';
    }

    function restoreProgressUI(caseId) {
      if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
      progressWidth = 0;
      currentStage = null;
      const saved = getCaseProgress(caseId);
      if (saved && saved.status) {
        setStage(caseId, saved.status, saved.counts || {}, { instant: true, widthOverride: saved.progress, skipPersist: true });
      } else {
        resetProgressUI();
      }
    }



    if (!Auth.getCurrentUser()) {
      window.location.href = '../login.html';
    }

    const urlParams = new URLSearchParams(window.location.search);
    const paragraphParam = urlParams.get('paragraph');

    


    // Add this helper to remove all timeupdate listeners from the audio element
    function resetAudioSync(audio) {
      // Remove all previous listeners by replacing the audio element
      stopAudioTicker();
      const newAudio = audio.cloneNode(true);
      newAudio.removeAttribute('data-ls-bound');
      audio.parentNode.replaceChild(newAudio, audio);
      activeAudioNode = newAudio;
      return newAudio;
    }

// Lightweight notification used on dashboard (matches app style)
function showNotification(message, type = 'success') {
  const existing = document.querySelector('.notification');
  if (existing) existing.remove();
  const n = document.createElement('div');
  n.className = `notification ${type}`;
  n.innerHTML = `<div class="icon">${type === 'error' ? '⚠️' : '✓'}</div><div>${message}</div>`;
  document.body.appendChild(n);
  setTimeout(() => { if (n && n.parentNode) { n.style.opacity='0'; setTimeout(()=> n.remove(), 300); } }, 3000);
}

function announceReadyUpdates(map) {
  if (!map) return;
  let updated = false;
  Object.entries(map).forEach(([caseId, payload]) => {
    if (!payload || payload.readyAt == null) return;
    const readyStamp = Number(payload.readyAt) || 0;
    const seen = Number(readySeen[caseId]) || 0;
    if (readyStamp > seen) {
      const name = payload.caseName || `Case ${caseId}`;
      showNotification(`"${name}" is ready to review.`, 'success');
      readySeen[caseId] = readyStamp;
      updated = true;
    }
  });
  if (updated) {
    writeSessionJSON(READY_SEEN_SESSION_KEY, readySeen);
  }
}

function recordCaseReady(caseId, caseName, readyAt) {
  if (!caseId) return;
  const map = readJSON(READY_STORAGE_KEY, {});
  const key = String(caseId);
  const existing = map[key] || {};
  const existingStamp = Number(existing.readyAt) || 0;
  let nextStamp = readyAt != null ? Number(readyAt) : NaN;
  if (!Number.isFinite(nextStamp)) {
    if (existingStamp) {
      if (caseName && (!existing.caseName || existing.caseName !== caseName)) {
        existing.caseName = caseName;
        map[key] = existing;
        writeJSON(READY_STORAGE_KEY, map);
      }
      return;
    }
    nextStamp = Date.now();
  } else if (existingStamp && nextStamp <= existingStamp) {
    if (caseName && (!existing.caseName || existing.caseName !== caseName)) {
      existing.caseName = caseName;
      map[key] = existing;
      writeJSON(READY_STORAGE_KEY, map);
    }
    return;
  }
  const resolvedName = caseName
    || existing.caseName
    || caseNameById.get(caseId)
    || `Case ${caseId}`;
  map[key] = { caseName: resolvedName, readyAt: nextStamp };
  writeJSON(READY_STORAGE_KEY, map);
  announceReadyUpdates(map);
}

function initReadyNotifications() {
  announceReadyUpdates(readJSON(READY_STORAGE_KEY, {}));
  window.addEventListener('storage', (event) => {
    if (event.key === READY_STORAGE_KEY) {
      try {
        const map = event.newValue ? JSON.parse(event.newValue) : {};
        announceReadyUpdates(map);
      } catch (_) {}
    }
  });
}

const SUPPORTED_TRANSCRIPT_EXTENSIONS = ['.txt', '.docx', '.pages'];
const SUPPORTED_TRANSCRIPT_MIME = [
  'text/plain',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.apple.pages'
];

function normalizeExtension(name = '') {
  const idx = name.lastIndexOf('.');
  if (idx === -1) return '';
  return name.slice(idx).toLowerCase();
}

function isSupportedTranscriptFile(file) {
  if (!file) return true;
  const ext = normalizeExtension(file.name || '');
  if (ext && SUPPORTED_TRANSCRIPT_EXTENSIONS.includes(ext)) return true;
  const mime = (file.type || '').toLowerCase();
  return SUPPORTED_TRANSCRIPT_MIME.includes(mime);
}

    // Update syncHighlight to set highlightedParagraphIndex
    function syncHighlight(audio, entries) {
      const container = document.getElementById('transcriptText');
      const paragraphs = container.querySelectorAll('.transcript-paragraph');
      const update = () => {
        const currentTime = getAudioCurrentTime(audio);
        if(currentTime >= old_start && currentTime < old_end) return;
        for (let i = 0; i < entries.length; i++) {
          const { start, end } = entries[i];
          const p = paragraphs[i];
          if (currentTime >= start && currentTime < end) {
            old_start = start;
            old_end = end;
            paragraphs.forEach(el => el.classList.remove('highlighted'));
            p.classList.add('highlighted');
            highlightedParagraphIndex = i;
            const containerRect = container.getBoundingClientRect();
            const pRect = p.getBoundingClientRect();
            if (pRect.top < containerRect.top || pRect.bottom > containerRect.bottom) {
              p.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
            break;
          }
        }
      };
      audio.addEventListener('timeupdate', update);
    }

    async function handleCreateCase() {
      const audioFile = caseAudioEl && caseAudioEl.files && caseAudioEl.files[0];
      const transcriptFile = caseTranscriptFileEl && caseTranscriptFileEl.files && caseTranscriptFileEl.files[0];
      const transcriptText = caseTranscriptTextEl && caseTranscriptTextEl.value && caseTranscriptTextEl.value.trim();
      const name = caseNameEl && caseNameEl.value && caseNameEl.value.trim();

      if (!audioFile) { showNotification('Please select an MP3 audio file.', 'error'); return; }
      if (transcriptFile && !isSupportedTranscriptFile(transcriptFile)) {
        showNotification('Transcript must be provided as TXT, DOCX, or Pages file.', 'error');
        return;
      }
      if (!transcriptFile && !transcriptText) { showNotification('Please provide a transcript (file or pasted text).', 'error'); return; }
      try {
        if (submitAddCase) { submitAddCase.disabled = true; submitAddCase.textContent = 'Uploading...'; }
        const res = await API.createCase({ name, audioFile, transcriptFile, transcriptText });
        // Reset form and close modal
        if (caseAudioEl) caseAudioEl.value = '';
        if (caseTranscriptFileEl) caseTranscriptFileEl.value = '';
        if (caseTranscriptTextEl) caseTranscriptTextEl.value = '';
        if (caseNameEl) caseNameEl.value = '';
        if (addCaseModal) addCaseModal.style.display = 'none';
        // Show toast after reload (persist message)
        sessionStorage.setItem('ls_toast_success', 'Case created. Alignment will start shortly.');
        window.location.reload();
      } catch (e) {
        console.error(e);
        showNotification('Failed to create case.', 'error');
      } finally {
        if (submitAddCase) { submitAddCase.disabled = false; submitAddCase.textContent = 'Upload'; }
      }
    }

    if (submitAddCase) {
      submitAddCase.addEventListener('click', handleCreateCase);
    }

    function getTranscriptContainer() {
      const container = document.getElementById('transcriptText');
      if (container) container.classList.remove('transcript-text-placeholder');
      return container;
    }

    function renderTranscript(audio, entries) {
      const container = getTranscriptContainer();
      if (!container) return;
      container.innerHTML = '';
      let lastPage = null;
      entries.forEach((entry, index) => {
        const page = entry && typeof entry.page === 'number' ? entry.page : null;
        if (page != null && page !== lastPage) {
          const marker = document.createElement('div');
          marker.className = 'page-marker';
          marker.textContent = `Page ${page}`;
          container.appendChild(marker);
          lastPage = page;
        }
        const p = document.createElement('p');
        p.textContent = entry.text;
        p.className = 'transcript-paragraph';
        p.dataset.start = entry.start;
        p.dataset.end = entry.end;
        p.dataset.index = index;
        if (page != null) p.dataset.page = page;

        p.addEventListener('click', () => {
          setAudioCurrentTime(entries[index].start);
          highlightedParagraphIndex = index; // Track highlighted paragraph
          //audio.play(); 
        });

        container.appendChild(p);
      });
    }

  
    function setupTranscript(rawText) {
      const parsed = JSON.parse(rawText);
      let audio = document.getElementById('transcriptAudio');
      // Reset audio element to remove previous listeners
      audio = resetAudioSync(audio);
      setupAudioControls(audio);
      renderTranscript(audio, parsed);
      syncHighlight(audio, parsed);
    }

    function renderKaraoke(audio, words) {
      const container = getTranscriptContainer();
      if (!container) return;
      container.innerHTML = '';
      words.forEach((w) => {
        const span = document.createElement('span');
        span.textContent = (w.word || '') + ' ';
        span.className = 'word';
        if (w.start != null) span.dataset.start = w.start;
        if (w.end != null) span.dataset.end = w.end;
        span.addEventListener('click', () => {
          if (w.start != null) setAudioCurrentTime(w.start);
        });
        container.appendChild(span);
      });
      audio.addEventListener('timeupdate', () => {
        const current = getAudioCurrentTime(audio);
        const spans = container.querySelectorAll('.word');
        let active = null;
        for (const el of spans) {
          const s = parseFloat(el.dataset.start);
          const e = parseFloat(el.dataset.end);
          if (!isNaN(s) && !isNaN(e) && current >= s && current <= e) {
            active = el;
            el.classList.add('highlighted');
          } else {
            el.classList.remove('highlighted');
          }
        }
        if (active) {
          try { active.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
        }
      });
      setupAudioControls(audio);
    }

    function renderKaraokeOriginal(audio, words, transcriptTextRaw, mapped) {
      const container = getTranscriptContainer();
      if (!container) return;
      container.innerHTML = '';
      // Split transcript into word and non-word segments, preserving exact punctuation and newlines
      const parts = transcriptTextRaw.split(/([\p{L}']+|[0-9][0-9.,–—-]*)/u);
      const norm = (s) => (s || '').toLocaleLowerCase().normalize('NFC').replace(/[^\p{L}']+/gu, '');
      const rnorm = words.map(w => norm(w.word));
      const NUM = {0:'zero',1:'one',2:'two',3:'three',4:'four',5:'five',6:'six',7:'seven',8:'eight',9:'nine'};
      const TEENS = {10:'ten',11:'eleven',12:'twelve',13:'thirteen',14:'fourteen',15:'fifteen',16:'sixteen',17:'seventeen',18:'eighteen',19:'nineteen'};
      const TENS = {2:'twenty',3:'thirty',4:'forty',5:'fifty',6:'sixty',7:'seventy',8:'eighty',9:'ninety'};
      function wordsUnder100(n){
        if (n<10) return [NUM[n]];
        if (n<20) return [TEENS[n]];
        const tens=Math.floor(n/10), ones=n%10;
        return ones? [TENS[tens], NUM[ones]] : [TENS[tens]];
      }
      function wordsUnder1000(n){
        if (n<100) return wordsUnder100(n);
        const hundreds=Math.floor(n/100), rest=n%100;
        return rest? [NUM[hundreds],'hundred',...wordsUnder100(rest)] : [NUM[hundreds],'hundred'];
      }
      function intToWordsEN(n){
        if (n===0) return [NUM[0]];
        if (n<1000) return wordsUnder1000(n);
        // up to 9999
        const thousands=Math.floor(n/1000), rest=n%1000;
        const left = thousands? [...wordsUnder100(thousands),'thousand'] : [];
        const right = rest? wordsUnder1000(rest) : [];
        return [...left, ...right];
      }
      function expandNumberToWords(token){
        // remove thousands separators
        const cleaned = token.replace(/,/g,'');
        if (cleaned.includes('.')){
          const [L,R] = cleaned.split('.',1).concat(cleaned.split('.').slice(1).join('.'));
          const left = parseInt(L||'0',10);
          const leftWords = isNaN(left)? [] : (String(left).length<=4 ? intToWordsEN(left) : String(left).split('').map(d=>NUM[parseInt(d,10)]));
          const rightWords = (R||'').split('').filter(ch=>/\d/.test(ch)).map(d=>NUM[parseInt(d,10)]);
          return [...leftWords,'point',...rightWords].filter(Boolean);
        }
        if (/[–—-]/.test(cleaned)){
          return cleaned.split(/[–—-]/).filter(Boolean).map(seg=>{
            const n = parseInt(seg,10);
            return isNaN(n)? [] : (String(seg).length<=4 ? intToWordsEN(n) : String(seg).split('').map(d=>NUM[parseInt(d,10)]));
          }).flat().flatMap((w,i,arr)=> i>0 && (arr[i-1]!== 'dash')? ['dash',w] : [w]);
        }
        const n = parseInt(cleaned,10);
        if (!isNaN(n)){
          return (String(cleaned).length<=4 ? intToWordsEN(n) : String(cleaned).split('').map(d=>NUM[parseInt(d,10)]));
        }
        return [];
      }
      // Build flat transcript token list (normalized), expanding numeric tokens into words
      const Tnorm = [];
      const tokenMeta = []; // maps each token to its source part and position
      const isAlpha = (s) => /^[\p{L}']+$/u.test(s);
      const isNum = (s) => /^[0-9][0-9.,–—-]*$/.test(s);
      parts.forEach((part, idx) => {
        if (!part) return;
        if (isAlpha(part)) {
          Tnorm.push(norm(part));
          tokenMeta.push({ partIndex: idx, type: 'alpha' });
        } else if (isNum(part)) {
          const exp = expandNumberToWords(part);
          exp.forEach((w, k) => {
            Tnorm.push(norm(w));
            tokenMeta.push({ partIndex: idx, type: 'num', subIndex: k, total: exp.length });
          });
        }
      });

      // Dynamic programming alignment in manageable blocks
      function alignDP(T, R) {
        const n = T.length, m = R.length;
        const score = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
        const back = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0)); // 0 diag, 1 up, 2 left
        for (let i = 1; i <= n; i++) { score[i][0] = i; back[i][0] = 1; }
        for (let j = 1; j <= m; j++) { score[0][j] = j; back[0][j] = 2; }
        for (let i = 1; i <= n; i++) {
          const Ti = T[i - 1];
          for (let j = 1; j <= m; j++) {
            const cost = (Ti === R[j - 1]) ? 0 : 1;
            let v = score[i - 1][j - 1] + cost; let d = 0;
            const up = score[i - 1][j] + 1; if (up < v) { v = up; d = 1; }
            const left = score[i][j - 1] + 1; if (left < v) { v = left; d = 2; }
            score[i][j] = v; back[i][j] = d;
          }
        }
        const map = new Array(n).fill(-1);
        let i = n, j = m;
        while (i > 0 || j > 0) {
          const d = back[i][j];
          if (i > 0 && j > 0 && d === 0) { map[i - 1] = j - 1; i--; j--; }
          else if (i > 0 && (j === 0 || d === 1)) { map[i - 1] = -1; i--; }
          else { j--; }
        }
        return map;
      }

      function alignBlocks(T, R, blockSize = 120, extra = 60) {
        const out = new Array(T.length).fill(-1);
        let rStart = 0; const Rlen = R.length;
        for (let t0 = 0; t0 < T.length; t0 += blockSize) {
          const t1 = Math.min(T.length, t0 + blockSize);
          const subT = T.slice(t0, t1);
          const windowLen = Math.min(Rlen - rStart, subT.length * 2 + extra);
          const rEnd = rStart + Math.max(0, windowLen);
          const subR = R.slice(rStart, rEnd);
          const map = alignDP(subT, subR);
          let last = -1;
          for (let i = 0; i < map.length; i++) {
            const j = map[i];
            if (j >= 0) { out[t0 + i] = rStart + j; last = rStart + j; }
          }
          if (last >= 0) rStart = Math.max(last + 1 - 8, rStart);
          else rStart = Math.min(Rlen, rStart + subT.length);
        }
        return out;
      }

      // If backend provided precise timings per split-part, prefer them
      let backendPartTimes = null;
      if (mapped && mapped.parts_times && Array.isArray(mapped.parts_times) && mapped.parts_times.length === parts.length) {
        backendPartTimes = mapped.parts_times;
      }
      const mapping = backendPartTimes ? null : alignBlocks(Tnorm, rnorm);

      // Render by consuming mapping tokens in order and aggregating over number groups
      let tokPtr = 0;
      parts.forEach((part, idx) => {
        if (!part) return;
        if (/^[\p{L}']+$/u.test(part)) {
          let s = undefined, e = undefined, mismatch = false;
          if (backendPartTimes) {
            const t = backendPartTimes[idx];
            if (t && t.start != null && t.end != null) { s = t.start; e = t.end; } else { mismatch = true; }
          } else {
            const j = tokPtr < mapping.length ? mapping[tokPtr++] : -1;
            const w = (j >= 0 ? words[j] : {}) || {};
            s = w.start; e = w.end;
            mismatch = (j < 0) || (norm(part) !== (j >= 0 ? rnorm[j] : ''));
          }
          const span = document.createElement('span');
          span.className = 'word' + (mismatch ? ' mismatch' : '');
          span.textContent = part;
          if (s != null) span.dataset.start = s;
          if (e != null) span.dataset.end = e;
          span.addEventListener('click', () => {
            if (span.dataset.start) setAudioCurrentTime(parseFloat(span.dataset.start));
          });
          container.appendChild(span);
        } else if (/^[0-9][0-9.,–—-]*$/.test(part)) {
          let s = undefined, e = undefined, mismatch = false;
          if (backendPartTimes) {
            const t = backendPartTimes[idx];
            if (t && t.start != null && t.end != null) { s = t.start; e = t.end; } else { mismatch = true; }
          } else {
            const exp = expandNumberToWords(part);
            const idxs = [];
            for (let k = 0; k < exp.length; k++) { idxs.push(tokPtr < mapping.length ? mapping[tokPtr++] : -1); }
            const slice = idxs.filter(j => j >= 0).map(j => words[j]).filter(Boolean);
            const starts = slice.map(x => x.start).filter(v => v != null);
            const ends = slice.map(x => x.end).filter(v => v != null);
            s = starts.length ? Math.min(...starts) : undefined;
            e = ends.length ? Math.max(...ends) : undefined;
            mismatch = idxs.some(j => j < 0);
          }
          const span = document.createElement('span');
          span.className = 'word number' + (mismatch ? ' mismatch' : '');
          span.textContent = part;
          if (s != null) span.dataset.start = s;
          if (e != null) span.dataset.end = e;
          span.addEventListener('click', () => {
            if (span.dataset.start) setAudioCurrentTime(parseFloat(span.dataset.start));
          });
          container.appendChild(span);
        } else {
          container.appendChild(document.createTextNode(part));
        }
      });

      audio.addEventListener('timeupdate', () => {
        const current = getAudioCurrentTime(audio);
        const spans = container.querySelectorAll('.word');
        let active = null;
        spans.forEach(el => {
          const s = parseFloat(el.dataset.start);
          const e = parseFloat(el.dataset.end);
          if (!isNaN(s) && !isNaN(e) && current >= s && current <= e) {
            active = el;
            el.classList.add('highlighted');
          } else {
            el.classList.remove('highlighted');
          }
        });
        if (active) {
          try { active.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (_) {}
        }
      });
    }


  async function showTranscriptPreview(data) {
    const previewPanel = document.getElementById('transcriptPreview');
    const transcriptText = document.getElementById('transcriptText');
    const audioSource = document.getElementById('audioSource');
    const audio = document.getElementById('transcriptAudio');

    previewPanel.style.display = 'block';
    if (data && data.id) {
      caseNameById.set(data.id, data.name || caseNameById.get(data.id) || `Case ${data.id}`);
    }
    if (transcriptText) {
      transcriptText.classList.remove('transcript-text-placeholder');
    }
    transcriptText.textContent = 'Loading transcript...';
    const token = sessionStorage.getItem('legalSyncToken');
    audioSource.src = `${window.location.origin}/stream/${data.audio_file}?token=${encodeURIComponent(token)}`;

    audio.load();
    setupAudioControls(audio);
    // Update progress estimate from audio duration when available
    audio.addEventListener('loadedmetadata', () => {
      const d = Math.max(1, audio.duration || 0);
      // Estimate total processing time roughly proportional to audio length (clamped)
      window.__ls_progress_est_ms = Math.min(900000, Math.max(60000, d * 1000));
    }, { once: true });

    try {
      const alignment = await API.getCaseAlignment(data.id);
      if (alignment && alignment.words) {
        const syncedAudio = resetAudioSync(audio);
        setupAudioControls(syncedAudio);
        // Try to fetch original transcript text and structured entries for mapping
        try {
          const [raw, entriesRes] = await Promise.all([
            API.getCaseTranscript(data.id),
            API.fetchProtected(`/text/${data.text_file}`)
          ]);
          if (entriesRes && entriesRes.content) {
            try { __entriesForActiveCase = JSON.parse(entriesRes.content); } catch (_) { __entriesForActiveCase = null; }
          } else {
            __entriesForActiveCase = null;
          }

          if (raw && raw.text) {
            renderKaraokeOriginal(syncedAudio, alignment.words, raw.text, alignment.mapped);
          } else {
            renderKaraoke(syncedAudio, alignment.words);
          }
          // After rendering words, enable flagging UI if we have entries
          if (__entriesForActiveCase && Array.isArray(__entriesForActiveCase)) {
            try { setupFlaggingUI(__entriesForActiveCase); } catch (e) { console.warn('Flagging setup failed:', e); }
          }
        } catch (_) {
          renderKaraoke(syncedAudio, alignment.words);
        }
      } else {
        const res = await API.fetchProtected(`text/${data.text_file}`);
        setupTranscript(res.content);
      }
  } catch (err) {
    transcriptText.textContent = 'Failed to load transcript text.';
    console.error(err);
  }

  // --------------- Dashboard word flagging (right-click) ---------------
  // Map rendered word spans to (entryIndex, wordOrdinal) using transcript entries.
  function buildWordMapping(entries) {
    const container = document.getElementById('transcriptText');
    if (!container) return;
    const spans = Array.from(container.querySelectorAll('.word'));
    if (!spans.length) return;

    // Build sequence of letter/number tokens across all entries with ordinals
    const wordlike = [];
    const isAlpha = (t) => /^[\p{L}']+$/u.test(t);
    const isNum = (t) => /^[0-9][0-9.,–—-]*$/.test(t);
    entries.forEach((entry, entryIndex) => {
      const tokens = String(entry.text || '').split(/(\s+)/);
      let ord = -1;
      tokens.forEach((tok, tokenIndex) => {
        const isWordToken = tok.trim().length > 0; // matches comments.js semantics
        if (isWordToken) {
          ord += 1;
          if (isAlpha(tok) || isNum(tok)) {
            wordlike.push({ entryIndex, tokenIndex, wordOrdinal: ord, text: tok });
          }
        }
      });
    });

    const n = Math.min(spans.length, wordlike.length);
    for (let i = 0; i < n; i++) {
      const s = spans[i];
      const t = wordlike[i];
      s.dataset.entryIndex = String(t.entryIndex);
      s.dataset.wordIndex = String(t.tokenIndex);
      s.dataset.wordOrdinal = String(t.wordOrdinal);
    }
  }

  function ensureNoDuplicateFlagIcon(entryIndex, wordOrdinal) {
    const container = document.getElementById('transcriptText');
    const sel = container && container.querySelector(
      `.flag-icon[data-entry-index="${entryIndex}"][data-word-ordinal="${wordOrdinal}"]`
    );
    return !!sel;
  }

  function insertFlagIconBeforeSpan(span, entryIndex, wordOrdinal) {
    if (!span) return; // nothing to do
    if (ensureNoDuplicateFlagIcon(entryIndex, wordOrdinal)) return;
    const icon = document.createElement('span');
    icon.className = 'flag-icon';
    icon.textContent = '❗';
    icon.title = 'Flagged';
    icon.dataset.entryIndex = String(entryIndex);
    icon.dataset.wordOrdinal = String(wordOrdinal);
    // Right-click on icon removes the flag
    icon.addEventListener('contextmenu', async (e) => {
      e.preventDefault(); e.stopPropagation();
      try {
        await removeFlag(parseInt(entryIndex,10), parseInt(wordOrdinal,10));
        if (icon.parentNode) icon.remove();
        showNotification('Flag removed', 'success');
      } catch (err) {
        console.error('Failed to remove flag', err);
        showNotification('Failed to remove flag', 'error');
  }
    });
    span.parentNode.insertBefore(icon, span);
  }

  function findWordSpan(entryIndex, wordOrdinal) {
    const container = document.getElementById('transcriptText');
    if (!container) return null;
    const ord = isNaN(wordOrdinal) ? 0 : wordOrdinal;
    let target = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-ordinal="${ord}"]`);
    if (!target) {
      target = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-index="${ord}"]`);
    }
    if (!target) {
      const candidates = Array.from(container.querySelectorAll(`.word[data-entry-index="${entryIndex}"]`));
      target = candidates.find(w => parseInt(w.dataset.wordOrdinal || '-1', 10) >= ord) || candidates[candidates.length - 1];
    }
    return target || null;
  }

  function ensureNoDuplicateCommentIcon(entryIndex, wordOrdinal) {
    const container = document.getElementById('transcriptText');
    const sel = container && container.querySelector(
      `.comment-icon[data-entry-index="${entryIndex}"][data-word-ordinal="${wordOrdinal}"]`
    );
    return !!sel;
  }

  function insertCommentIndicatorBeforeSpan(span, entryIndex, wordOrdinal) {
    if (!span) return;
    if (ensureNoDuplicateCommentIcon(entryIndex, wordOrdinal)) return;
    const icon = document.createElement('span');
    icon.className = 'comment-icon';
    icon.textContent = '!';
    icon.title = 'Comment available';
    icon.setAttribute('aria-hidden', 'true');
    icon.dataset.entryIndex = String(entryIndex);
    icon.dataset.wordOrdinal = String(wordOrdinal);
    span.dataset.hasComment = 'true';
    span.parentNode.insertBefore(icon, span);
  }

  function paintPageBreaks(entries) {
    const container = document.getElementById('transcriptText');
    if (!container) return;
    container.querySelectorAll('.page-marker').forEach((node) => node.remove());
    if (!Array.isArray(entries) || !entries.length) return;
    let lastPage = null;
    entries.forEach((entry, entryIndex) => {
      const page = entry && typeof entry.page === 'number' ? entry.page : null;
      if (page == null || page === lastPage) return;
      let target = container.querySelector(`.word[data-entry-index="${entryIndex}"]`);
      if (!target) {
        target = container.querySelector(`.transcript-paragraph[data-index="${entryIndex}"]`);
      }
      const marker = document.createElement('div');
      marker.className = 'page-marker';
      marker.textContent = `Page ${page}`;
      if (target && target.parentNode) {
        target.parentNode.insertBefore(marker, target);
      } else {
        container.appendChild(marker);
      }
      lastPage = page;
    });
  }

  function showFlagPopup(x, y, onYes) {
    // Remove any existing popup first
    document.querySelectorAll('.flag-popup').forEach(el => el.remove());
    const pop = document.createElement('div');
    pop.className = 'flag-popup';
    pop.style.left = `${Math.max(6, Math.min(x, window.innerWidth - 240))}px`;
    pop.style.top = `${Math.max(6, Math.min(y, window.innerHeight - 80))}px`;
    pop.innerHTML = `
      <div class="title">Do you want to flag this word?</div>
      <div class="actions">
        <button class="cancel">Cancel</button>
        <button class="primary yes">Yes</button>
      </div>
    `;
    document.body.appendChild(pop);
    const close = () => { try { pop.remove(); } catch(_){} document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
    const onDoc = (e) => { if (!pop.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    pop.querySelector('.cancel').addEventListener('click', (e) => { e.preventDefault(); close(); });
    pop.querySelector('.yes').addEventListener('click', async (e) => { e.preventDefault(); try { await onYes(); } finally { close(); } });
    setTimeout(() => { document.addEventListener('mousedown', onDoc); document.addEventListener('keydown', onKey); }, 0);
  }

  async function saveEntry(entryIndex, updatedEntry) {
    const caseId = activeCaseId;
    if (caseId == null) throw new Error('No active case');
    await API.postProtected(`text/${caseId}/entry/${entryIndex}`, {
      body: JSON.stringify(updatedEntry)
    });
  }

  async function addFlag(entryIndex, wordOrdinal) {
    if (!__entriesForActiveCase || !Array.isArray(__entriesForActiveCase)) throw new Error('Transcript entries not loaded');
    const idx = parseInt(entryIndex, 10);
    const ord = parseInt(wordOrdinal, 10);
    const entry = __entriesForActiveCase[idx];
    if (!entry) throw new Error('Invalid entry');
    entry.comments = entry.comments || [];
    const exists = entry.comments.some(c => String((c.internal_comment||'').trim().toLowerCase()) === 'flagged' && parseInt(c.start_word,10) === ord);
    if (exists) { showNotification('Already flagged'); return false; }
    entry.comments.push({ start_word: ord, end_word: ord, internal_comment: 'flagged', external_comment: '' });
    await saveEntry(idx, entry);
    return true;
  }

  async function removeFlag(entryIndex, wordOrdinal) {
    if (!__entriesForActiveCase || !Array.isArray(__entriesForActiveCase)) throw new Error('Transcript entries not loaded');
    const idx = parseInt(entryIndex, 10);
    const ord = parseInt(wordOrdinal, 10);
    const entry = __entriesForActiveCase[idx];
    if (!entry || !Array.isArray(entry.comments)) return;
    const before = entry.comments.length;
    entry.comments = entry.comments.filter(c => !(String((c.internal_comment||'').trim().toLowerCase()) === 'flagged' && parseInt(c.start_word,10) === ord));
    if (entry.comments.length === before) return; // nothing to remove
    await saveEntry(idx, entry);
  }

  function attachWordContextMenus() {
    const container = document.getElementById('transcriptText');
    if (!container) return;
    container.querySelectorAll('.word').forEach((span) => {
      span.addEventListener('contextmenu', (e) => {
        // Only handle if mapping is available
        if (!span.dataset || span.dataset.entryIndex == null || span.dataset.wordOrdinal == null) return;
        e.preventDefault(); e.stopPropagation();
        const entryIndex = parseInt(span.dataset.entryIndex, 10);
        const wordOrdinal = parseInt(span.dataset.wordOrdinal, 10);
        showFlagPopup(e.clientX, e.clientY, async () => {
          try {
            const ok = await addFlag(entryIndex, wordOrdinal);
            if (ok) {
              insertFlagIconBeforeSpan(span, entryIndex, wordOrdinal);
              showNotification('Flag added', 'success');
            }
          } catch (err) {
            console.error('Failed to add flag', err);
            showNotification('Failed to add flag', 'error');
          }
        });
      });
    });
  }

  function paintExistingFlags(entries) {
    const container = document.getElementById('transcriptText');
    if (!container) return;
    entries.forEach((entry, entryIndex) => {
      (entry.comments || []).forEach((c) => {
        if (String((c.internal_comment||'').trim().toLowerCase()) !== 'flagged') return;
        const ord = parseInt(c.start_word, 10);
        const target = findWordSpan(entryIndex, isNaN(ord) ? 0 : ord);
        if (target) {
          const resolved = isNaN(ord) ? (parseInt(target.dataset.wordOrdinal, 10) || 0) : ord;
          insertFlagIconBeforeSpan(target, entryIndex, resolved);
        }
      });
    });
  }

  function paintCommentIndicators(entries) {
    const container = document.getElementById('transcriptText');
    if (!container) return;
    entries.forEach((entry, entryIndex) => {
      (entry.comments || []).forEach((comment) => {
        const internal = (comment.internal_comment || '').trim();
        const external = (comment.external_comment || '').trim();
        const hasText = Boolean(internal) || Boolean(external);
        const isFlagOnly = internal.toLowerCase() === 'flagged' && !external;
        if (!hasText || isFlagOnly) return;
        const ord = parseInt(comment.start_word, 10);
        const target = findWordSpan(entryIndex, isNaN(ord) ? 0 : ord);
        if (target) {
          const resolved = isNaN(ord) ? (parseInt(target.dataset.wordOrdinal, 10) || 0) : ord;
          insertCommentIndicatorBeforeSpan(target, entryIndex, resolved);
        }
      });
    });
  }

  function setupFlaggingUI(entries) {
    // Map spans -> (entryIndex, ord)
    buildWordMapping(entries);
    // Attach right-click handler to words
    attachWordContextMenus();
    // Render existing flags (old + new)
    paintExistingFlags(entries);
    paintCommentIndicators(entries);
    paintPageBreaks(entries);
  }

  previewPanel.style.display = 'block';
    
  }

  document.addEventListener('DOMContentLoaded', async () => {
  // Show persisted toast message if any
  const toast = sessionStorage.getItem('ls_toast_success');
  if (toast) {
    showNotification(toast, 'success');
    sessionStorage.removeItem('ls_toast_success');
  }
  initReadyNotifications();
  const token = sessionStorage.getItem('legalSyncToken');
  const listContainer = document.getElementById('transcriptItems');
  const spinner = document.getElementById('loadingSpinner');

  if (!token) {
    listContainer.innerText = "You must be logged in.";
    return;
  }

  spinner.style.display = 'block';

  try {
    const response = await API.fetchProtected('cases');
    const cases = await response;
    spinner.style.display = 'none';

    if (cases.length === 0) {
      listContainer.innerText = "No transcripts found.";
      return;
    }

    let currentActive = null;

  cases.forEach(caseItem => {
    caseNameById.set(caseItem.id, caseItem.name);
    const el = document.createElement('div');
    el.className = 'transcript-item';
    el.textContent = caseItem.name;
    el.innerHTML = `
      <div class="transcript-row">
        <div class="transcript-title">${caseItem.name}</div>
        <div class="item-actions">
          <button class="comments-btn" data-id="${caseItem.id}">View Comments</button>
          <button class="kebab-btn" aria-haspopup="true" aria-expanded="false">⋮</button>
          <div class="action-menu" role="menu">
            <button class="menu-item delete" data-del-id="${caseItem.id}">Delete</button>
          </div>
        </div>
      </div>
    `;
      el.querySelector('.comments-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      const caseId = e.target.dataset.id;
      let paragraphParam = '';
      if (highlightedParagraphIndex !== null) {
        paragraphParam = `&paragraph=${highlightedParagraphIndex}`;
      }
      window.location.href = `comments.html?case=${caseId}${paragraphParam}`;
    });
    const kebabBtn = el.querySelector('.kebab-btn');
    const menu = el.querySelector('.action-menu');
    const delBtn = el.querySelector('[data-del-id]');
    // Insert rename as first item
    if (menu && !menu.querySelector('[data-rename-id]')) {
      const renameBtn = document.createElement('button');
      renameBtn.className = 'menu-item';
      renameBtn.setAttribute('role','menuitem');
      renameBtn.textContent = 'Rename';
      renameBtn.setAttribute('data-rename-id', String(caseItem.id));
      menu.insertBefore(renameBtn, menu.firstChild);
      renameBtn.addEventListener('click', (e)=>{
        e.stopPropagation();
        pendingRenameCaseId = caseItem.id;
        if (renameCaseInput) renameCaseInput.value = caseItem.name;
        if (renameCaseModal) renameCaseModal.style.display='flex';
        menu.classList.remove('open');
      });
    }
    if (kebabBtn && menu) {
      kebabBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = menu.classList.contains('open');
        document.querySelectorAll('.action-menu.open').forEach(m => {
          m.classList.remove('open');
          const row = m.closest('.transcript-item');
          if (row) row.classList.remove('menu-open');
        });
        if (!isOpen) { menu.classList.add('open'); const row = menu.closest('.transcript-item'); if (row) row.classList.add('menu-open'); }
      });
      document.addEventListener('click', () => { menu.classList.remove('open'); const row = menu.closest('.transcript-item'); if (row) row.classList.remove('menu-open'); });
    }
    if (delBtn) {
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        pendingDeleteCaseId = parseInt(e.currentTarget.getAttribute('data-del-id'), 10);
        if (deleteCaseModal) deleteCaseModal.style.display = 'flex';
      });
    }


        el.dataset.caseId = caseItem.id;
        el.style.cursor = 'pointer';

        el.addEventListener('click', async () => {
          activeCaseId = caseItem.id;
          restoreProgressUI(caseItem.id);
          if (currentActive) currentActive.classList.remove('active');
          el.classList.add('active');
          currentActive = el;

          // Always reload preview, even if same case
          try {
            const data = await API.fetchProtected(`cases/${caseItem.id}`);
            if (data && data.id) {
              caseNameById.set(data.id, data.name || caseItem.name || `Case ${data.id}`);
            }
            await showTranscriptPreview(data);
            startStatusPolling(caseItem.id);
          } catch (err) {
            console.error('Error loading case:', err);
            showNotification('Failed to load case', 'error');
          }
        });

      listContainer.appendChild(el);

      
    });
    const urlParams = new URLSearchParams(window.location.search);
    const caseParam = urlParams.get('case');
    const paragraphParam = urlParams.get('paragraph');

  if (caseParam) {
    const caseObj = cases.find(c => c.id === parseInt(caseParam, 10)); // Fix comparison
    console.log('Case object:', caseObj);
    if (caseObj) {
      activeCaseId = caseObj.id;
      restoreProgressUI(caseObj.id);
      const data = await API.fetchProtected(`cases/${caseObj.id}`);
      if (data && data.id) {
        caseNameById.set(data.id, data.name || caseObj.name || `Case ${data.id}`);
      }
      await showTranscriptPreview(data);
      startStatusPolling(caseObj.id);
      if (paragraphParam !== null) {
        const index = parseInt(paragraphParam, 10);
        setTimeout(() => {
          const paragraphs = document.querySelectorAll('.transcript-paragraph');
          const audio = document.getElementById('transcriptAudio');
          if (paragraphs[index]) {
            paragraphs[index].scrollIntoView({ behavior: 'smooth', block: 'center' });
            const start = paragraphs[index].dataset.start;
            if (start) {
              setAudioCurrentTime(parseFloat(start));
            }
          }
        }, 400); // Wait for transcript to render
      }
    }
  }
  } catch (err) {
    console.error('Failed to load cases:', err);
    spinner.style.display = 'none';
    listContainer.innerText = 'Failed to load transcripts.';
    showNotification('Failed to load transcripts', 'error');
  }

});

// Indeterminate stage-based progress animation (no backend progress dependency)
let progressTimer = null;
let currentStage = null;
let progressWidth = 0;
function setStage(caseId, status, counts = {}, options = {}) {
  if (!status) return;
  const { instant = false, widthOverride = null, skipPersist = false } = options;
  const label = document.getElementById('alignLabel');
  const bar = document.getElementById('alignProgress');
  const wrap = document.getElementById('alignStatus');
  if (!bar || !wrap) return;

  const targets = { queued: 5, converting: 18, splitting: 20, aligning: 85, building: 95 };
  const texts = {
    queued: 'Queued',
    converting: 'Converting audio…',
    splitting: 'Splitting audio…',
    aligning: 'Aligning transcript…',
    building: 'Finalizing…',
    failed: 'Failed',
    done: 'Ready to review'
  };
  const clampWidth = (value) => Math.max(0, Math.min(100, value));
  const prev = getCaseProgress(caseId);
  const prevStatus = prev && prev.status;
  const cleanedCounts = (counts && (counts.total_chunks || counts.completed_chunks)) ? {
    total_chunks: Number(counts.total_chunks) || 0,
    completed_chunks: Number(counts.completed_chunks) || 0
  } : null;

  const updateLabel = () => {
    if (!label) return;
    if (status === 'aligning' && counts && counts.total_chunks) {
      const cur = Math.min(counts.completed_chunks || 0, counts.total_chunks);
      label.textContent = `Aligning chunk ${cur}/${counts.total_chunks}`;
    } else {
      label.textContent = texts[status] || 'Working…';
    }
  };

  if (status === 'done' || status === 'failed') {
    const caseName = caseNameById.get(caseId);
    if (wrap) wrap.style.display = status === 'failed' ? 'flex' : 'none';
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
    currentStage = null;
    bar.classList.remove('active', 'failed', 'ready');
    if (status === 'failed') {
      bar.classList.add('failed');
    } else {
      bar.classList.add('ready');
    }
    const width = clampWidth(widthOverride != null ? widthOverride : 100);
    progressWidth = width;
    bar.style.width = width + '%';
    updateLabel();
    if (!skipPersist) {
      persistCaseProgress(caseId, {
        status,
        progress: width,
        counts: cleanedCounts,
        updatedAt: Date.now()
      });
      if (status === 'done' && prevStatus !== 'done') {
        recordCaseReady(caseId, caseName);
      }
    }
    return;
  }

  if (progressTimer && currentStage !== status) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
  if (wrap) wrap.style.display = 'flex';

  currentStage = status;
  bar.classList.remove('failed', 'ready');
  bar.classList.add('active');
  updateLabel();

  if (instant) {
    const width = clampWidth(widthOverride != null ? widthOverride : (prev && prev.status === status ? prev.progress : (targets[status] || 0)));
    progressWidth = width;
    bar.style.width = width + '%';
  } else if (!progressTimer) {
    const tick = 300;
    const est = window.__ls_progress_est_ms || 120000; // default 2 minutes
    const step = (95 / (est / tick));
    progressTimer = setInterval(() => {
      let dynamicTarget = targets[status] || 90;
      if (status === 'aligning' && counts && counts.total_chunks) {
        const ratio = Math.min(1, Math.max(0, (counts.completed_chunks || 0) / counts.total_chunks));
        dynamicTarget = 20 + 65 * ratio;
      }
      const cur = typeof progressWidth === 'number' && progressWidth > 0
        ? progressWidth
        : (parseFloat(bar.style.width || '0') || 0);
      const next = Math.min(cur + step, dynamicTarget);
      progressWidth = next;
      bar.style.width = next + '%';
    }, tick);
  }

  if (!skipPersist) {
    const storedWidth = clampWidth(progressWidth || parseFloat(bar.style.width || '0') || 0);
    persistCaseProgress(caseId, {
      status,
      progress: storedWidth,
      counts: cleanedCounts,
      updatedAt: Date.now()
    });
  }
}

let statusInterval = null;
function startStatusPolling(caseId) {
  clearInterval(statusInterval);
  const allowed = { queued:1, converting:1, splitting:1, aligning:1, building:1, done:1, failed:1 };

  let pollingActive = true;
  const tickStatus = async () => {
    try {
      const s = await API.getCaseStatus(caseId);
      if (s && s.status && allowed[s.status]) {
        setStage(caseId, s.status, { total_chunks: s.total_chunks, completed_chunks: s.completed_chunks });
      } else {
        resetProgressUI();
      }
      if (s && (s.status === 'done' || s.status === 'failed')) {
        pollingActive = false;
        clearInterval(statusInterval);
        if (s.status === 'done' && activeCaseId === caseId) {
          try {
            const data = await API.fetchProtected(`cases/${caseId}`);
            await showTranscriptPreview(data);
          } catch (_) {}
        }
      }
    } catch (_) {}
  };

  tickStatus().then(() => {
    if (!pollingActive) return;
    statusInterval = setInterval(() => { tickStatus(); }, 1500);
  });
}
