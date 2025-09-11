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
          await API.deleteCase(pendingDeleteCaseId);
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
        if (transcriptFileName) transcriptFileName.textContent = caseTranscriptFileEl.files && caseTranscriptFileEl.files[0] ? caseTranscriptFileEl.files[0].name : 'No file chosen';
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
      if (wrap) wrap.style.display = 'none';
      if (bar) { bar.style.width = '0%'; bar.classList.remove('active','failed','ready'); }
      if (label) label.textContent = '';
      if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
      progressWidth = 0; currentStage = null;
    }



    if (!Auth.getCurrentUser()) {
      window.location.href = '../login.html';
    }

    const urlParams = new URLSearchParams(window.location.search);
    const paragraphParam = urlParams.get('paragraph');

    


    // Add this helper to remove all timeupdate listeners from the audio element
function resetAudioSync(audio) {
  // Remove all previous listeners by replacing the audio element
  const newAudio = audio.cloneNode(true);
  audio.parentNode.replaceChild(newAudio, audio);
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

    // Update syncHighlight to set highlightedParagraphIndex
    function syncHighlight(audio, entries) {
      const container = document.getElementById('transcriptText');
      const paragraphs = container.querySelectorAll('.transcript-paragraph');
      audio.addEventListener('timeupdate', () => {
        const currentTime = audio.currentTime;
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
      });
    }

    async function handleCreateCase() {
      const audioFile = caseAudioEl && caseAudioEl.files && caseAudioEl.files[0];
      const transcriptFile = caseTranscriptFileEl && caseTranscriptFileEl.files && caseTranscriptFileEl.files[0];
      const transcriptText = caseTranscriptTextEl && caseTranscriptTextEl.value && caseTranscriptTextEl.value.trim();
      const name = caseNameEl && caseNameEl.value && caseNameEl.value.trim();

      if (!audioFile) { showNotification('Please select an MP3 audio file.', 'error'); return; }
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

    function renderTranscript(audio, entries) {
      const container = document.getElementById('transcriptText');
      container.innerHTML = '';
    
      entries.forEach((entry, index) => {
        const p = document.createElement('p');
        p.textContent = entry.text;
        p.className = 'transcript-paragraph';
        p.dataset.start = entry.start;
        p.dataset.end = entry.end;
        p.dataset.index = index;

        p.addEventListener('click', () => {
          audio.currentTime = entries[index].start;
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
      renderTranscript(audio, parsed);
      syncHighlight(audio, parsed);
    }

    function renderKaraoke(audio, words) {
      const container = document.getElementById('transcriptText');
      container.innerHTML = '';
      words.forEach((w) => {
        const span = document.createElement('span');
        span.textContent = (w.word || '') + ' ';
        span.className = 'word';
        if (w.start != null) span.dataset.start = w.start;
        if (w.end != null) span.dataset.end = w.end;
        span.addEventListener('click', () => { if (w.start != null) audio.currentTime = w.start; });
        container.appendChild(span);
      });
      audio.addEventListener('timeupdate', () => {
        const current = audio.currentTime;
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
    }

    function renderKaraokeOriginal(audio, words, transcriptTextRaw) {
      const container = document.getElementById('transcriptText');
      container.innerHTML = '';
      // Split transcript into word and non-word segments, preserving exact punctuation and newlines
      const parts = transcriptTextRaw.split(/([A-Za-z']+|[0-9][0-9.,–—-]*)/);
      let wi = 0;
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
      parts.forEach(part => {
        if (part === '') return;
        if (/^[A-Za-z']+$/.test(part)) {
          const w = words[wi++] || {};
          const span = document.createElement('span');
          span.className = 'word';
          span.textContent = part;
          if (w.start != null) span.dataset.start = w.start;
          if (w.end != null) span.dataset.end = w.end;
          span.addEventListener('click', () => { if (span.dataset.start) audio.currentTime = parseFloat(span.dataset.start); });
          container.appendChild(span);
        } else if (/^[0-9][0-9.,–—-]*$/.test(part)) {
          // Aggregate timing from the number of expanded words consumed by aligner
          const exp = expandNumberToWords(part);
          const slice = words.slice(wi, wi + exp.length);
          wi += exp.length;
          const starts = slice.map(x=>x.start).filter(v=>v!=null);
          const ends = slice.map(x=>x.end).filter(v=>v!=null);
          const s = starts.length? Math.min(...starts): undefined;
          const e = ends.length? Math.max(...ends): undefined;
          const span = document.createElement('span');
          span.className = 'word number';
          span.textContent = part;
          if (s!=null) span.dataset.start = s;
          if (e!=null) span.dataset.end = e;
          span.addEventListener('click', ()=>{ if (span.dataset.start) audio.currentTime = parseFloat(span.dataset.start); });
          container.appendChild(span);
        } else {
          container.appendChild(document.createTextNode(part));
        }
      });

      audio.addEventListener('timeupdate', () => {
        const current = audio.currentTime;
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
    transcriptText.textContent = 'Loading transcript...';
    const token = sessionStorage.getItem('legalSyncToken');
    audioSource.src = `${window.location.origin}/stream/${data.audio_file}?token=${encodeURIComponent(token)}`;

    audio.load();
    // Update progress estimate from audio duration when available
    audio.addEventListener('loadedmetadata', () => {
      const d = Math.max(1, audio.duration || 0);
      // Estimate total processing time roughly proportional to audio length (clamped)
      window.__ls_progress_est_ms = Math.min(900000, Math.max(60000, d * 1000));
    }, { once: true });

    try {
      const alignment = await API.getCaseAlignment(data.id);
      if (alignment && alignment.words) {
        const a = resetAudioSync(audio);
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
            renderKaraokeOriginal(a, alignment.words, raw.text);
          } else {
            renderKaraoke(a, alignment.words);
          }
          // After rendering words, enable flagging UI if we have entries
          if (__entriesForActiveCase && Array.isArray(__entriesForActiveCase)) {
            try { setupFlaggingUI(__entriesForActiveCase); } catch (e) { console.warn('Flagging setup failed:', e); }
          }
        } catch (_) {
          renderKaraoke(a, alignment.words);
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
    const isAlpha = (t) => /^[A-Za-z']+$/.test(t);
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
        // Try by ordinal first
        let target = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-ordinal="${ord}"]`);
        if (!target) {
          // Fallback by token index
          target = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-index="${ord}"]`);
        }
        if (!target) {
          // Fallback: nearest later word in same entry
          const candidates = Array.from(container.querySelectorAll(`.word[data-entry-index="${entryIndex}"]`));
          target = candidates.find(w => parseInt(w.dataset.wordOrdinal || '-1', 10) >= ord) || candidates[candidates.length - 1];
        }
        if (target) insertFlagIconBeforeSpan(target, entryIndex, isNaN(ord) ? (parseInt(target.dataset.wordOrdinal,10) || 0) : ord);
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
          resetProgressUI();
          if (currentActive) currentActive.classList.remove('active');
          el.classList.add('active');
          currentActive = el;

          // Always reload preview, even if same case
          try {
            const data = await API.fetchProtected(`cases/${caseItem.id}`);
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
      resetProgressUI();
      const data = await API.fetchProtected(`cases/${caseObj.id}`);
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
            if (audio && start) {
              audio.currentTime = parseFloat(start);
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
function setStage(status, counts){
  const label = document.getElementById('alignLabel');
  const bar = document.getElementById('alignProgress');
  const wrap = document.getElementById('alignStatus');
  const targets = { queued: 5, converting: 18, splitting: 20, aligning: 85, building: 95 };
  const texts = {
    queued: 'Queued',
    converting: 'Converting audio…',
    splitting: 'Splitting audio…',
    aligning: 'Aligning transcript…',
    building: 'Finalizing…',
    failed: 'Failed',
    done: 'Ready'
  };
  if (status === 'done') {
    if (wrap) wrap.style.display = 'none';
    if (bar) { bar.style.width = '100%'; bar.classList.remove('active'); bar.classList.add('ready'); }
    if (label) label.textContent = texts[status];
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
    progressWidth = 100;
    currentStage = null;
    return;
  }
  if (status === 'failed') {
    if (wrap) wrap.style.display = 'block';
    if (bar) { bar.style.width = '100%'; bar.classList.remove('active','ready'); bar.classList.add('failed'); }
    if (label) label.textContent = texts[status];
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
    progressWidth = 100;
    currentStage = null;
    return;
  }
  // Show wrapper and animate within stage bounds
  if (wrap) wrap.style.display = 'block';
  if (label) {
    if (status === 'aligning' && counts && counts.total_chunks) {
      const cur = Math.min(counts.completed_chunks || 0, counts.total_chunks);
      label.textContent = `Aligning chunk ${cur}/${counts.total_chunks}`;
    } else {
      label.textContent = texts[status] || 'Working…';
    }
  }
  if (!bar) return;
  bar.classList.remove('failed','ready');
  bar.classList.add('active');
  const target = targets[status] || 90;
  if (currentStage !== status) {
    currentStage = status;
    if (progressTimer) { clearInterval(progressTimer); }
    const est = window.__ls_progress_est_ms || 120000; // 2 min default
    const tick = 300;
    const step = (95 / (est / tick)); // reach ~95% over est time
    progressTimer = setInterval(()=>{
      // Monotonic increase toward current stage target (or chunk-based)
      let dynamicTarget = target;
      if (status === 'aligning' && counts && counts.total_chunks) {
        const r = Math.min(1, Math.max(0, (counts.completed_chunks || 0) / counts.total_chunks));
        dynamicTarget = 20 + 65 * r; // 20%..85%
      }
      const cur = progressWidth || (parseFloat(bar.style.width || '0') || 0);
      const next = Math.min(cur + step, dynamicTarget);
      progressWidth = next;
      bar.style.width = next + '%';
    }, tick);
  }
}

let statusInterval = null;
function startStatusPolling(caseId) {
  clearInterval(statusInterval);
  // immediate tick
  (async () => {
    try {
      const s = await API.getCaseStatus(caseId);
      const allowed = { queued:1, converting:1, splitting:1, aligning:1, building:1 };
      if (s && s.status && allowed[s.status]) setStage(s.status, { total_chunks: s.total_chunks, completed_chunks: s.completed_chunks }); else resetProgressUI();
    } catch(_){}
  })();
  statusInterval = setInterval(async () => {
    try {
      const s = await API.getCaseStatus(caseId);
      const allowed = { queued:1, converting:1, splitting:1, aligning:1, building:1 };
      if (s && s.status && allowed[s.status]) setStage(s.status, { total_chunks: s.total_chunks, completed_chunks: s.completed_chunks }); else resetProgressUI();
      if (s.status === 'done' || s.status === 'failed') {
        clearInterval(statusInterval);
        if (s.status === 'done' && activeCaseId === caseId) {
          try {
            const data = await API.fetchProtected(`cases/${caseId}`);
            await showTranscriptPreview(data);
          } catch (_) {}
        }
      }
    } catch (_) {}
  }, 1500);
}
