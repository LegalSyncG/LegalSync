    import { API } from '../shared/api.js';

    const urlParams = new URLSearchParams(window.location.search);
    const caseId = urlParams.get('case');
    const container = document.getElementById('commentContainer');
    const scroller = document.querySelector('.transcript-container');
    const commentForm = document.getElementById('commentForm');
    const existingComments = document.getElementById('existingComments');
    const searchInput = document.getElementById('searchTranscript');
    const searchPrevBtn = document.getElementById('searchPrev');
    const searchNextBtn = document.getElementById('searchNext');
    const searchCounter = document.getElementById('searchCounter');
    const clearSearchIcon = document.getElementById('clearSearchIcon');
    const searchModeToggle = document.getElementById('searchModeToggle');
    const searchContainer = document.querySelector('.search-container');
    const transcriptContainer = document.querySelector('.transcript-container');
    const editPanel = document.getElementById('editPanel');
    const saveEditBtn = document.getElementById('saveEditBtn');
    const cancelEditBtn = document.getElementById('cancelEditBtn');
    const cancelSelectBtn = document.getElementById('cancelSelectBtn');
    const paragraphAudio = document.getElementById('paragraphAudio');
    const READY_STORAGE_KEY = 'ls_case_ready_map';
    const READY_SEEN_SESSION_KEY = 'ls_ready_seen_map';

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

    let readySeen = readSessionJSON(READY_SEEN_SESSION_KEY, {});
    let currentCaseName = '';

    function announceReadyUpdates(map) {
      if (!map) return;
      let updated = false;
      Object.entries(map).forEach(([caseKey, payload]) => {
        if (!payload || payload.readyAt == null) return;
        const readyStamp = Number(payload.readyAt) || 0;
        const seen = Number(readySeen[caseKey]) || 0;
        if (readyStamp > seen) {
          const name = payload.caseName || `Case ${caseKey}`;
          showNotification(`"${name}" is ready to review.`, 'success');
          readySeen[caseKey] = readyStamp;
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
      const resolvedName = caseName || existing.caseName || `Case ${caseId}`;
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

    let currentSelection = { entryIndex: null, start: null, end: null };
    let transcriptData = [];
    let currentEditingComment = null;
    let activeComment = null;

    // Inline segment playback state
    let segmentGuard = { enabled: false, end: 0 };
    let currentlyPlayingIndex = null;

    initReadyNotifications();

    function configureAudioForCase(caseData) {
      if (!paragraphAudio || !caseData) return;
      const token = sessionStorage.getItem('legalSyncToken');
      paragraphAudio.preload = 'auto';
      paragraphAudio.src = `${window.location.origin}/stream/${caseData.audio_file}?token=${encodeURIComponent(token || '')}`;
      // Install a single guard that pauses playback at segment end
      if (!configureAudioForCase._installed) {
        paragraphAudio.addEventListener('timeupdate', () => {
          if (segmentGuard.enabled && paragraphAudio.currentTime >= segmentGuard.end) {
            paragraphAudio.pause();
            segmentGuard.enabled = false;
            currentlyPlayingIndex = null;
            updateAllPlayIcons();
          }
        });
        paragraphAudio.addEventListener('pause', () => {
          // Update icons on manual pause
          updateAllPlayIcons();
        });
        paragraphAudio.addEventListener('play', () => {
          // Update icons on resume
          updateAllPlayIcons();
        });
        configureAudioForCase._installed = true;
      }
    }

    function playSegment(start, end) {
      if (!paragraphAudio) return;
      // Ensure metadata loaded before seeking (some browsers)
      const seekAndPlay = () => {
        try { paragraphAudio.currentTime = Math.max(0, start || 0); } catch (_) {}
        segmentGuard.end = Math.max(0, end || 0);
        segmentGuard.enabled = Number.isFinite(segmentGuard.end) && segmentGuard.end > (start || 0);
        paragraphAudio.play().catch(() => {/* user gesture may be required */});
      };

      if (paragraphAudio.readyState >= 1) {
        seekAndPlay();
      } else {
        const onMeta = () => { paragraphAudio.removeEventListener('loadedmetadata', onMeta); seekAndPlay(); };
        paragraphAudio.addEventListener('loadedmetadata', onMeta);
        // In case src not yet loaded
        try { paragraphAudio.load(); } catch (_) {}
      }
    }

    function togglePlayForEntry(entryIndex) {
      const entry = transcriptData && transcriptData[entryIndex];
      if (!entry || entry.start == null || entry.end == null) {
        showNotification('Audio timing not available for this paragraph.');
        return;
      }
      // If switching paragraphs, always start from its start
      if (currentlyPlayingIndex !== entryIndex) {
        currentlyPlayingIndex = entryIndex;
        playSegment(entry.start, entry.end);
        updateAllPlayIcons();
        return;
      }
      // Same paragraph: toggle pause/resume
      if (paragraphAudio.paused) {
        // If out of bounds, restart
        if (paragraphAudio.currentTime < entry.start || paragraphAudio.currentTime >= entry.end) {
          playSegment(entry.start, entry.end);
        } else {
          segmentGuard.end = entry.end; segmentGuard.enabled = true;
          paragraphAudio.play().catch(()=>{});
        }
      } else {
        paragraphAudio.pause();
      }
      updateAllPlayIcons();
    }

    function nudgeEntry(entryIndex, deltaSeconds) {
      const entry = transcriptData && transcriptData[entryIndex];
      if (!entry || entry.start == null || entry.end == null || !paragraphAudio) return;
      const cur = paragraphAudio.currentTime || entry.start;
      const endMargin = Math.max(entry.start, entry.end - 0.05); // avoid overshooting end
      const unclamped = cur + deltaSeconds;
      const target = Math.min(endMargin, Math.max(entry.start, unclamped));
      try { paragraphAudio.currentTime = target; } catch (_) {}
      // Keep guard to paragraph end if playing
      if (!paragraphAudio.paused) { segmentGuard.end = entry.end; segmentGuard.enabled = true; }
    }

    function updateAllPlayIcons() {
      const icons = document.querySelectorAll('.play-icon');
      icons.forEach((btn) => {
        const idx = parseInt(btn.dataset.entryIndex, 10);
        const playing = (idx === currentlyPlayingIndex) && !paragraphAudio.paused;
        btn.classList.toggle('playing', playing);
        btn.textContent = playing ? '⏸' : '▶';
        btn.setAttribute('aria-label', playing ? `Pause paragraph ${idx + 1}` : `Play paragraph ${idx + 1}`);
        btn.title = playing ? 'Pause' : 'Play';
      });
    }

    function startStatusWatcher(caseId, caseName) {
      if (!caseId) return;
      let lastStatus = null;

      const poll = async () => {
        try {
          const status = await API.getCaseStatus(caseId);
          if (!status || !status.status) return;
          if (status.status !== lastStatus) {
            lastStatus = status.status;
            if (status.status === 'done') {
              recordCaseReady(caseId, caseName);
            } else if (status.status === 'failed') {
              const name = caseName || `Case ${caseId}`;
              showNotification(`Alignment failed for "${name}".`, 'error');
            }
          }
        } catch (err) {
          console.warn('Status watcher error:', err);
        }
      };

      poll();
      const interval = setInterval(poll, 4000);
      window.addEventListener('beforeunload', () => clearInterval(interval));
    }

    // No dynamic tools visibility needed: nudges are revealed via CSS on hover

    // Removed SVG nudge icon; using tiny text buttons "-3" and "+3"

    // Search state
    const searchState = {
      query: '',
      matches: [], // For transcript mode: { entryIndex, startOrd, endOrd }
      current: -1,
      mode: 'transcript', // 'transcript' | 'comments'
    };

    // Debounce helper
    function debounce(fn, wait = 150) {
      let t;
      return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), wait);
      };
    }

    // Funkcja do wyświetlania powiadomień
    function showNotification(message, type = 'error') {
      const existing = document.querySelector('.notification');
      if (existing) existing.remove();
      
      const notification = document.createElement('div');
      notification.className = `notification ${type}`;
      notification.innerHTML = `
        <div class="icon">${type === 'error' ? '⚠️' : '✓'}</div>
        <div>${message}</div>
      `;
      
      document.body.appendChild(notification);
      
      setTimeout(() => {
        if (notification.parentNode) {
          notification.style.opacity = '0';
          setTimeout(() => notification.remove(), 300);
        }
      }, 3000);
    }

    // Funkcja do wyświetlania potwierdzenia usunięcia
    function showDeleteConfirmation(entryIndex, commentIndex) {
      const modal = document.createElement('div');
      modal.className = 'confirmation-modal';
      modal.innerHTML = `
        <div class="confirmation-box">
          <h3>Delete Comment</h3>
          <p>Are you sure you want to delete this comment?</p>
          <div class="confirmation-buttons">
            <button class="cancel-btn">Cancel</button>
            <button class="confirm-btn">Delete</button>
          </div>
        </div>
      `;
      
      document.body.appendChild(modal);
      
      modal.querySelector('.cancel-btn').addEventListener('click', () => {
        modal.remove();
      });
      
      modal.querySelector('.confirm-btn').addEventListener('click', async () => {
        modal.remove();
        try {
          transcriptData[entryIndex].comments.splice(commentIndex, 1);
          await saveTranscript(entryIndex);
          renderComments(transcriptData);
          showNotification("Comment deleted successfully!", "success");
        } catch (err) {
          console.error("Failed to delete comment:", err);
          showNotification("Error deleting comment.", "error");
        }
      });
    }

    if (!caseId) {
      container.textContent = "Invalid case ID.";
    } else {
      loadTranscriptWithComments(caseId);
    }

    async function loadTranscriptWithComments(caseId) {
      try {
        showNotification("Loading transcript...", "success");
        const caseData = await API.fetchProtected(`cases/${caseId}`);
        const transcriptRes = await API.fetchProtected(`/text/${caseData.text_file}`);
        currentCaseName = caseData.name || currentCaseName || '';
        if (!startStatusWatcher._started) {
          startStatusWatcher(caseId, currentCaseName);
          startStatusWatcher._started = true;
        }
        transcriptData = JSON.parse(transcriptRes.content);
        configureAudioForCase(caseData);
        renderComments(transcriptData);

        // Scroll to paragraph if specified in URL
        const paragraphParam = urlParams.get('paragraph');
        if (paragraphParam !== null) {
          const entryBox = document.querySelector(`.entry-box[data-entry-index="${paragraphParam}"]`);
          if (entryBox) {
            setTimeout(() => {
              entryBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 100); // W
          }
        }
      } catch (error) {
        console.error('Failed to load transcript or comments:', error);
        container.textContent = 'Failed to load transcript.';
      }
    }

    // Utility: normalize text for case-insensitive compare
    function norm(s) { return (s || '').toLowerCase(); }

    // Build transcript matches for current query
    function buildTranscriptMatches(query) {
      const q = norm(query).trim();
      if (!q) return [];

      const matches = [];
      const entryBoxes = container.querySelectorAll('.entry-box');
      entryBoxes.forEach((entryBox) => {
        const entryIndex = parseInt(entryBox.dataset.entryIndex, 10);
        const words = Array.from(entryBox.querySelectorAll('.word'));
        const wNorms = words.map(w => norm(w.textContent));

        if (q.indexOf(' ') === -1) {
          // Single term: substring match within a single word
          wNorms.forEach((wn, i) => {
            if (wn.includes(q)) matches.push({ entryIndex, startOrd: i, endOrd: i });
          });
        } else {
          // Phrase: match across consecutive words by equality of spaced join
          const qWords = q.split(/\s+/).filter(Boolean);
          const k = qWords.length;
          for (let i = 0; i + k - 1 < wNorms.length; i++) {
            const segment = wNorms.slice(i, i + k).join(' ');
            if (segment === q) {
              matches.push({ entryIndex, startOrd: i, endOrd: i + k - 1 });
            }
          }
        }
      });
      return matches;
    }

    // Apply transcript highlights for matches/current
    function applyTranscriptHighlights(matches, currentIndex) {
      // Clear previous
      container.querySelectorAll('.word.search-match, .word.search-current').forEach(el => {
        el.classList.remove('search-match');
        el.classList.remove('search-current');
      });

      matches.forEach((m, idx) => {
        const para = container.querySelector(`.entry-box[data-entry-index="${m.entryIndex}"]`);
        if (!para) return;
        const words = para.querySelectorAll('.word');
        for (let i = m.startOrd; i <= m.endOrd; i++) {
          const w = words[i];
          if (!w) continue;
          w.classList.add('search-match');
          if (idx === currentIndex) w.classList.add('search-current');
        }
      });
    }

    // Scroll to current transcript match
    // Scroll to current match using native scrollIntoView like comments navigation

    function scrollToCurrentImmediate() {
      const m = searchState.matches[searchState.current];
      if (!m) return;
      const para = container.querySelector(`.entry-box[data-entry-index="${m.entryIndex}"]`);
      if (!para) return;
      const first = para.querySelector(`.word[data-word-ordinal="${m.startOrd}"]`) || para.querySelectorAll('.word')[m.startOrd];
      if (first) {
        try {
          first.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
        } catch (_) {
          try { first.scrollIntoView(true); } catch (_) {}
        }
      }
    }

    function updateCounter() {
      if (!searchCounter) return;
      const total = searchState.matches.length;
      const current = searchState.current >= 0 ? searchState.current + 1 : 0;
      searchCounter.textContent = `${current}/${total}`;
    }

    function clearTranscriptHighlights() {
      container.querySelectorAll('.word.search-match, .word.search-current').forEach(el => {
        el.classList.remove('search-match');
        el.classList.remove('search-current');
      });
    }

    function clearSearch(silent = false) {
      searchState.query = '';
      searchState.matches = [];
      searchState.current = -1;
      if (searchInput) searchInput.value = '';
      clearTranscriptHighlights();
      // Reset comment filtering
      if (searchState.mode === 'comments') applyCommentFilter('');
      updateCounter();
      if (!silent) {
        // no notification needed; aria-live counter updates
      }
      updateEngagedSticky();
    }

    function runSearch({ scroll = false, notifyNoMatch = false } = {}) {
      const query = searchInput ? searchInput.value : '';
      searchState.query = query;
      // mode comes from toggle button state
      
      if (!query.trim()) {
        clearSearch(true);
        return;
      }
      updateEngagedSticky();

      if (searchState.mode === 'transcript') {
        const matches = buildTranscriptMatches(query);
        searchState.matches = matches;
        if (matches.length === 0) {
          clearTranscriptHighlights();
          if (notifyNoMatch) showNotification('No matches found.');
          searchState.current = -1;
        } else {
          // Keep current within range, default to first
          if (searchState.current < 0 || searchState.current >= matches.length) searchState.current = 0;
        }
        applyTranscriptHighlights(searchState.matches, searchState.current);
        updateCounter();
        if (scroll && searchState.current !== -1) scrollToCurrentImmediate();
      } else {
        // comments mode
        clearTranscriptHighlights();
        applyCommentFilter(query);
        const cmatches = buildCommentMatches(query);
        searchState.matches = cmatches;
        if (cmatches.length === 0) {
          if (notifyNoMatch) showNotification('No matches found.');
          searchState.current = -1;
        } else {
          if (searchState.current < 0 || searchState.current >= cmatches.length) searchState.current = 0;
        }
        updateCounter();
        if (scroll && searchState.current !== -1) scrollToCurrentComment();
      }
    }

    // Build comment matches and filter helpers
    function buildCommentMatches(query) {
      const q = norm(query).trim();
      if (!q) return [];
      const results = [];
      transcriptData.forEach((entry, entryIndex) => {
        (entry.comments || []).forEach((c, commentIndex) => {
          const t = `${c.internal_comment || ''} ${c.external_comment || ''}`;
          if (norm(t).includes(q)) {
            results.push({ entryIndex, commentIndex });
          }
        });
      });
      return results;
    }

    function applyCommentFilter(query) {
      const q = norm(query).trim();
      const items = Array.from(document.querySelectorAll('#existingComments .comment-item'));
      if (!items.length) return;
      items.forEach((el) => {
        const text = norm(el.textContent || '');
        const match = q ? text.includes(q) : true;
        el.style.display = match ? '' : 'none';
      });
      requestAnimationFrame(() => positionCommentItems());
    }

    function scrollToCurrentComment() {
      const m = searchState.matches[searchState.current];
      if (!m) return;
      // Activate the comment so it gets the 'active' style
      activeComment = { entryIndex: m.entryIndex, commentIndex: m.commentIndex };
      updateCommentPanel();
      // Re-apply filter after re-render
      applyCommentFilter(searchState.query);
      // Scroll to it
      requestAnimationFrame(() => {
        const el = document.querySelector(`.comment-item[data-entry-index="${m.entryIndex}"][data-comment-index="${m.commentIndex}"]`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }

    function positionCommentItems() {
      const items = Array.from(document.querySelectorAll('#existingComments .comment-item'));
      const rightList = document.getElementById('existingComments');
      if (!rightList) return;
      const rightRect = rightList.getBoundingClientRect();

      const positioned = [];
      items.forEach((div) => {
        const entryIndex = parseInt(div.dataset.entryIndex, 10);
        const startWord = parseInt(div.dataset.startWord, 10);
        const para = container.querySelector(`.entry-box[data-entry-index="${entryIndex}"]`);
        if (!para) return;
        // Prefer ordinal (saved format); fall back to token index only if needed
        const target = para.querySelector(`.word[data-word-ordinal="${startWord}"]`) 
                    || para.querySelector(`.word[data-word-index="${startWord}"]`);
        if (!target) return;
        const wordRect = target.getBoundingClientRect();
        const y = wordRect.top - rightRect.top; // align with right list visual top
        positioned.push({ div, y, h: (div.offsetHeight || 1) });
      });

      // stack with spacing to avoid overlaps
      positioned.sort((a,b) => {
        const dy = a.y - b.y;
        if (dy !== 0) return dy;
        const ae = parseInt(a.div.dataset.entryIndex, 10) - parseInt(b.div.dataset.entryIndex, 10);
        if (ae !== 0) return ae;
        return parseInt(a.div.dataset.commentIndex, 10) - parseInt(b.div.dataset.commentIndex, 10);
      });
      let lastBottom = -Infinity;
      const spacing = 8;
      let maxBottom = 0;
      positioned.forEach(it => {
        const top = Math.max(it.y, lastBottom + spacing);
        it.div.style.position = 'absolute';
        it.div.style.left = '12px';
        it.div.style.right = '12px';
        it.div.style.top = `${top}px`;
        lastBottom = top + it.h;
        if (lastBottom > maxBottom) maxBottom = lastBottom;
      });

      // ensure container height
      rightList.style.height = Math.max(container.scrollHeight, maxBottom + 20) + 'px';
    }

    function positionSelectedForm(entryIndex, wordIndex) {
      const section = document.getElementById('selectedCommentSection');
      const para = container.querySelector(`.entry-box[data-entry-index="${entryIndex}"]`);
      if (!para) return;
      const target = para.querySelector(`.word[data-word-index="${wordIndex}"]`);
      if (!target) return;
      const scrollerRect = scroller.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const top = targetRect.top - scrollerRect.top + scroller.scrollTop + 16; // a bit lower than word
      section.style.display = 'block';
      section.style.top = `${top}px`;
    }

    function renderComments(data) {
      container.innerHTML = '';
      let lastPage = null;
      data.forEach((entry, entryIndex) => {
        const page = entry && typeof entry.page === 'number' ? entry.page : null;
        if (page != null && page !== lastPage) {
          const pageLabel = document.createElement('div');
          pageLabel.className = 'page-label';
          pageLabel.textContent = `Page ${page}`;
          container.appendChild(pageLabel);
          lastPage = page;
        }
        const entryDiv = document.createElement('div');
        entryDiv.className = 'entry-box';
        entryDiv.dataset.entryIndex = entryIndex;

        const textEl = document.createElement('p');
        const tokens = entry.text.split(/(\s+)/);
        let wordOrdinal = -1;
        tokens.forEach((token, tokenIndex) => {
          const span = document.createElement('span');
          span.textContent = token;
          span.dataset.entryIndex = entryIndex;
          const isWord = token.trim().length > 0;
          if (isWord) {
            wordOrdinal += 1;
            span.classList.add('word');
            // Preserve original semantics: data-word-index holds token index
            span.dataset.wordIndex = String(tokenIndex);
            span.dataset.wordOrdinal = String(wordOrdinal);

            span.addEventListener('click', (e) => {
              e.stopPropagation();
              // Pass token index for selection to preserve saved format
              handleWordClick(entryIndex, tokenIndex);
            });

            span.addEventListener('mouseenter', () => {
              if (span.classList.contains('commented')) { span.style.backgroundColor = '#cce5ff'; }
            });
            
            span.addEventListener('mouseleave', () => {
              if (span.classList.contains('commented')) { span.style.backgroundColor = ''; }
            });
          }

          textEl.appendChild(span);
        });

        // After building all words for this paragraph, underline each comment's exact length range
        const wordsInPara = Array.from(textEl.querySelectorAll('.word'));
        (entry.comments || []).forEach((c) => {
          const len = Math.abs(parseInt(c.end_word, 10) - parseInt(c.start_word, 10)) + 1;
          // Resolve start ordinal: prefer ordinal match, fallback from token index
          let startOrd = (() => {
            const ordMatch = textEl.querySelector(`.word[data-word-ordinal="${c.start_word}"]`);
            if (ordMatch && ordMatch.dataset.wordOrdinal) return parseInt(ordMatch.dataset.wordOrdinal, 10);
            const tokMatch = textEl.querySelector(`.word[data-word-index="${c.start_word}"]`);
            if (tokMatch && tokMatch.dataset.wordOrdinal) return parseInt(tokMatch.dataset.wordOrdinal, 10);
            return parseInt(c.start_word, 10);
          })();
          const endOrd = Math.min(wordsInPara.length - 1, startOrd + len - 1);
          for (let o = startOrd; o <= endOrd; o++) {
            const w = wordsInPara[o];
            if (w) w.classList.add('commented');
          }
        });

        // Render comments icons
        (entry.comments || []).forEach((comment, commentIndex) => {
          // Add icon only to the first word of the commented range
          // Try first by token index; fallback by ordinal index
          const startSpan = textEl.querySelector(`.word[data-word-ordinal="${comment.start_word}"]`) 
                           || textEl.querySelector(`.word[data-word-index="${comment.start_word}"]`);
          if (startSpan) {
            const icon = document.createElement('span');
            icon.textContent = '❗';
            icon.title = 'Show comment';
            icon.style.cursor = 'pointer';
            icon.style.marginRight = '4px';
            icon.style.fontSize = '1em';
            icon.style.verticalAlign = 'middle';

            icon.addEventListener('click', (e) => {
              e.stopPropagation();
              // Highlight comment in panel
              activeComment = { entryIndex, commentIndex };
              updateCommentPanel();
              // Highlight word range by length starting exactly at startSpan ordinal
              const len = Math.abs(parseInt(comment.end_word,10) - parseInt(comment.start_word,10)) + 1;
              const startOrd = parseInt(startSpan.dataset.wordOrdinal, 10);
              highlightWordRange(entryIndex, startOrd, startOrd + len - 1);
              // Scroll to comment panel
              setTimeout(() => {
                const commentDiv = document.querySelector(
                  `.comment-item[data-entry-index="${entryIndex}"][data-comment-index="${commentIndex}"]`
                );
                if (commentDiv) {
                  commentDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
              }, 100);
            });

            textEl.insertBefore(icon, startSpan);
          }
        });

        // Small circular Play button
        const playBtn = document.createElement('button');
        playBtn.className = 'play-icon';
        playBtn.type = 'button';
        playBtn.dataset.entryIndex = String(entryIndex);
        playBtn.textContent = '▶';
        playBtn.setAttribute('aria-label', `Play paragraph ${entryIndex + 1}`);
        playBtn.title = 'Play';
        playBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          togglePlayForEntry(entryIndex);
        });

        // Two tiny circular nudges (-3 / +3) appearing left of play
        const nudges = document.createElement('div');
        nudges.className = 'nudge-wrap';
        nudges.dataset.entryIndex = String(entryIndex);
        const nRew = document.createElement('button');
        nRew.type = 'button';
        nRew.className = 'nudge-circle nudge-rew';
        nRew.setAttribute('aria-label', `Rewind 3 seconds paragraph ${entryIndex + 1}`);
        nRew.title = 'Rewind 3s';
        nRew.textContent = '-3';
        nRew.addEventListener('click', (e) => {
          e.stopPropagation();
          nudgeEntry(entryIndex, -3);
        });
        const nFwd = document.createElement('button');
        nFwd.type = 'button';
        nFwd.className = 'nudge-circle nudge-fwd';
        nFwd.setAttribute('aria-label', `Forward 3 seconds paragraph ${entryIndex + 1}`);
        nFwd.title = 'Forward 3s';
        nFwd.textContent = '+3';
        nFwd.addEventListener('click', (e) => {
          e.stopPropagation();
          nudgeEntry(entryIndex, 3);
        });
        nudges.appendChild(nRew);
        nudges.appendChild(nFwd);

        entryDiv.appendChild(textEl);

        entryDiv.append(playBtn);
        entryDiv.append(nudges);
        container.appendChild(entryDiv);
      });

      updateCommentPanel();
      // After comments are rendered, position them aligned with transcript
      requestAnimationFrame(() => positionCommentItems());
      // Re-apply search highlights/filter if user has an active query
      reapplySearchIfNeeded();
      // Ensure icons reflect current audio state
      updateAllPlayIcons();
    }

    // Build selection by clicking first and last word (no panel opening here)
    function handleWordClick(entryIndex, wordIndex) {
      // Convert token index to ordinal for consistent selection
      const tokEl = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-index="${wordIndex}"]`);
      const ord = tokEl && tokEl.dataset.wordOrdinal ? parseInt(tokEl.dataset.wordOrdinal, 10) : wordIndex;
      if (currentSelection.entryIndex !== entryIndex) {
        clearWordSelection();
        currentSelection = { entryIndex, start: ord, end: ord };
        const el = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-ordinal="${ord}"]`);
        if (el) el.classList.add('selectedRange');
      } else {
        if (currentSelection.start == null) {
          currentSelection.entryIndex = entryIndex;
          currentSelection.start = ord;
          const el = container.querySelector(`.word[data-entry-index="${entryIndex}"][data-word-ordinal="${ord}"]`);
          if (el) el.classList.add('selectedRange');
        } else {
          currentSelection.entryIndex = entryIndex;
          currentSelection.end = ord;
          highlightWordRange(entryIndex, currentSelection.start, currentSelection.end);
          // Auto open add panel after finishing selection by clicks
          const s = Math.min(currentSelection.start, currentSelection.end);
          positionSelectedForm(entryIndex, s);
        }
      }
    }

    function highlightWordRange(entryIndex, start, end) {
      // Treat inputs as ordinals; callers convert as needed.
      clearWordSelection();
      const [s, e] = [Math.min(start, end), Math.max(start, end)];
      const spans = container.querySelectorAll(`.word[data-entry-index="${entryIndex}"]`);
      for (let i = s; i <= e; i++) {
        const target = spans[i];
        if (target) target.classList.add('selectedRange');
      }
      
      currentSelection.start = s;
      currentSelection.end = e;
      currentSelection.entryIndex = entryIndex;
    }

    function clearWordSelection() {
      container.querySelectorAll('.word.selected, .word.selectedRange').forEach(el => {
        el.classList.remove('selected');
        el.classList.remove('selectedRange');
      });
      currentSelection = { entryIndex: null, start: null, end: null };
    }

    // Text selection to choose comment range
    container.addEventListener('mouseup', () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) return;
      const range = sel.getRangeAt(0);
      if (!range) return;
      if (!container.contains(range.commonAncestorContainer)) return;

      const words = Array.from(container.querySelectorAll('.word'));
      const selectedWords = words.filter(w => {
        try { return range.intersectsNode(w); } catch (e) { return false; }
      });
      if (!selectedWords.length) return;

      const entryIdx = selectedWords[0].dataset.entryIndex;
      if (selectedWords.some(w => w.dataset.entryIndex !== entryIdx)) {
        showNotification('Please select within a single paragraph.');
        sel.removeAllRanges();
        return;
      }

      const indices = selectedWords.map(w => parseInt(w.dataset.wordOrdinal, 10)).sort((a,b)=>a-b);
      const entryNum = parseInt(entryIdx,10);
      // compute selection and show add-comment panel immediately
      const startOrd = indices[0];
      const endOrd = indices[indices.length-1];
      highlightWordRange(entryNum, startOrd, endOrd);
      positionSelectedForm(entryNum, startOrd);
      // keep native selection for visual feedback
    });

    // Show add-comment panel on right click / two-finger tap
    container.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (currentSelection.entryIndex == null) return;
      positionSelectedForm(currentSelection.entryIndex, currentSelection.start ?? 0);
    });

    // Hide add-comment panel when clicking outside of it
    document.addEventListener('mousedown', (e) => {
      const panel = document.getElementById('selectedCommentSection');
      if (!panel || panel.style.display === 'none') return;
      if (!panel.contains(e.target)) {
        panel.style.display = 'none';
        clearWordSelection();
      }
    });

    // Close any open kebab menus when clicking outside
    document.addEventListener('mousedown', (e) => {
      document.querySelectorAll('#existingComments .menu.open').forEach(m => {
        if (!m.contains(e.target)) m.classList.remove('open');
      });
    });

    // Reposition comments and floating form on scroll for perfect alignment
    let scrollRaf = false;
    (scroller || container).addEventListener('scroll', () => {
      if (scrollRaf) return;
      scrollRaf = true;
      requestAnimationFrame(() => {
        scrollRaf = false;
        positionCommentItems();
        const panel = document.getElementById('selectedCommentSection');
        if (panel && panel.style.display !== 'none' && currentSelection.entryIndex != null) {
          positionSelectedForm(currentSelection.entryIndex, currentSelection.start ?? 0);
        }
        // Keep fixed search aligned while scrolling
        updateFixedPosition();
      });
    });

    commentForm.onsubmit = async (e) => {
      e.preventDefault();
        
      const { entryIndex, start, end } = currentSelection;
        
      if (entryIndex == null || start == null || end == null) {
        showNotification("Please select a word range.");
        return;
      }
  
      const internal = document.getElementById('internalComment').value.trim();
      const external = document.getElementById('externalComment').value.trim();
      
      // Wymagaj przynajmniej jednego komentarza
      if (!internal && !external) {
        showNotification("Please enter at least one comment.");
        return;
      }

      const comment = {
        start_word: Math.min(start, end),
        end_word: Math.max(start, end),
        internal_comment: internal,
        external_comment: external,
      };

      transcriptData[entryIndex].comments = transcriptData[entryIndex].comments || [];
      transcriptData[entryIndex].comments.push(comment);
  
      // Clear the form and selection
      document.getElementById('internalComment').value = '';
      document.getElementById('externalComment').value = '';
      clearWordSelection();
      
      try {
        await saveTranscript(entryIndex);
        renderComments(transcriptData);
        showNotification("Comment added successfully!", "success");
        // Hide the floating add panel and clear any selection
        const panel = document.getElementById('selectedCommentSection');
        if (panel) panel.style.display = 'none';
        clearWordSelection();
      } catch (err) {
        console.error("Failed to save comment:", err);
        showNotification("Error saving comment.", "error");
      }
    };

    // Cancel selection and hide floating panel
    if (cancelSelectBtn) {
      cancelSelectBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const panel = document.getElementById('selectedCommentSection');
        if (panel) panel.style.display = 'none';
        clearWordSelection();
      });
    }

    function updateCommentPanel() {
      existingComments.innerHTML = '';
      transcriptData.forEach((entry, entryIndex) => {
        (entry.comments || []).forEach((comment, i) => {
          const div = document.createElement('div');
          div.className = 'comment-item';
          if (activeComment && activeComment.entryIndex === entryIndex && activeComment.commentIndex === i) {
            div.classList.add('active');
          }
          div.dataset.entryIndex = entryIndex;
          div.dataset.commentIndex = i;
          div.dataset.startWord = comment.start_word;

          const p = document.createElement('p');
          const paragraphLabel = `Paragraph ${entryIndex + 1}, words ${comment.start_word + 1}-${comment.end_word + 1}`;
          p.innerHTML = `
            <strong>${paragraphLabel}</strong><br>
            ${comment.internal_comment ? `<em>Internal:</em> ${comment.internal_comment}<br>` : ''}
            ${comment.external_comment ? `<em>External:</em> ${comment.external_comment}` : ''}
          `;
          div.appendChild(p);

          // Kebab icon and contextual menu
          const kebab = document.createElement('div');
          kebab.className = 'kebab';
          kebab.title = 'More actions';
          kebab.textContent = '⋮';
          kebab.addEventListener('click', (e) => {
            e.stopPropagation();
            // close others
            document.querySelectorAll('#existingComments .menu.open').forEach(m => m.classList.remove('open'));
            menu.classList.toggle('open');
          });

          const menu = document.createElement('div');
          menu.className = 'menu';
          // prevent outside click handler from closing when interacting with menu
          menu.addEventListener('mousedown', (e) => e.stopPropagation());
          const editAction = document.createElement('button');
          editAction.textContent = 'Edit';
          editAction.addEventListener('click', (e) => {
            e.stopPropagation();
            menu.classList.remove('open');
            startEditComment(entryIndex, i);
          });
          const deleteAction = document.createElement('button');
          deleteAction.textContent = 'Delete';
          deleteAction.addEventListener('click', (e) => {
            e.stopPropagation();
            showDeleteConfirmation(entryIndex, i);
          });

          menu.appendChild(editAction);
          menu.appendChild(deleteAction);
          div.appendChild(kebab);
          div.appendChild(menu);

          div.addEventListener('click', () => {
            activeComment = { entryIndex, commentIndex: i };
            updateCommentPanel();
            highlightWordRange(entryIndex, comment.start_word, comment.end_word);
            const para = container.querySelector(`.entry-box[data-entry-index="${entryIndex}"]`);
            if (para) {
              para.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
          });

          existingComments.appendChild(div);
        });
      });

      requestAnimationFrame(() => positionCommentItems());
    }

    function startEditComment(entryIndex, commentIndex) {
      // Inline edit inside the comment item
      const div = document.querySelector(`.comment-item[data-entry-index="${entryIndex}"][data-comment-index="${commentIndex}"]`);
      if (!div) return;
      // Prevent multiple editors
      if (div.querySelector('.inline-edit')) return;
      // bring this comment visually to front
      div.classList.add('active');
      div.classList.add('editing');
      const comment = transcriptData[entryIndex].comments[commentIndex];

      const editor = document.createElement('div');
      editor.className = 'inline-edit';
      editor.innerHTML = `
        <textarea class="internal" rows="2" placeholder="Internal comment...">${comment.internal_comment || ''}</textarea>
        <textarea class="external" rows="2" placeholder="External comment...">${comment.external_comment || ''}</textarea>
        <div class="actions">
          <button class="save">Save</button>
          <button class="cancel">Cancel</button>
        </div>
      `;

      const save = editor.querySelector('.save');
      const cancel = editor.querySelector('.cancel');
      // Prevent global mousedown handlers from interfering with typing
      editor.addEventListener('mousedown', (e) => { e.stopPropagation(); });
      editor.addEventListener('click', (e) => { e.stopPropagation(); });
      save.addEventListener('click', async (e) => {
        e.preventDefault();
        const internal = editor.querySelector('.internal').value.trim();
        const external = editor.querySelector('.external').value.trim();
        if (!internal && !external) {
          showNotification('Please enter at least one comment.');
          return;
        }
        transcriptData[entryIndex].comments[commentIndex].internal_comment = internal;
        transcriptData[entryIndex].comments[commentIndex].external_comment = external;
        try {
          await saveTranscript(entryIndex);
          renderComments(transcriptData);
          showNotification('Comment updated successfully!', 'success');
        } catch (err) {
          console.error('Failed to update comment:', err);
          showNotification('Error updating comment.', 'error');
        }
      });
      cancel.addEventListener('click', (e) => {
        e.preventDefault();
        editor.remove();
        div.classList.remove('editing');
        positionCommentItems();
      });

      // Attach editor to the comment item
      div.appendChild(editor);
      // Ensure visible
      editor.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      // Rerun layout to avoid overlapping neighbors
      positionCommentItems();
    }

    saveEditBtn.onclick = async (e) => {
      e.preventDefault();
      if (!currentEditingComment) return;
      
      const { entryIndex, commentIndex } = currentEditingComment;
      const internal = document.getElementById('editInternal').value.trim();
      const external = document.getElementById('editExternal').value.trim();
      
      // Wymagaj przynajmniej jednego komentarza
      if (!internal && !external) {
        showNotification("Please enter at least one comment.");
        return;
      }

      transcriptData[entryIndex].comments[commentIndex].internal_comment = internal;
      transcriptData[entryIndex].comments[commentIndex].external_comment = external;
      
      try {
        await saveTranscript(entryIndex);
        editPanel.style.display = 'none';
        renderComments(transcriptData);
        showNotification("Comment updated successfully!", "success");
      } catch (err) {
        console.error("Failed to update comment:", err);
        showNotification("Error updating comment.", "error");
      }
    };

    cancelEditBtn.onclick = (e) => {
      e.preventDefault();
      editPanel.style.display = 'none';
      currentEditingComment = null;
    };

    async function saveTranscript(entryIndex) {
      const updatedEntry = transcriptData[entryIndex];
      try {
        await API.postProtected(`text/${caseId}/entry/${entryIndex}`, {
          body: JSON.stringify(updatedEntry),
        });
      } catch (err) {
        console.error("Failed to save entry:", err);
        throw err;
      }
    }

    // Search: wire up UI
    if (clearSearchIcon) {
      clearSearchIcon.addEventListener('click', () => clearSearch());
    }

    const onSearchInput = debounce(() => {
      runSearch({ scroll: false, notifyNoMatch: false });
    }, 200);

    if (searchInput) {
      searchInput.addEventListener('input', onSearchInput);
      searchInput.addEventListener('focus', () => updateEngagedSticky());
      searchInput.addEventListener('blur', () => setTimeout(updateEngagedSticky, 0));
      searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          updateEngagedSticky();
          e.preventDefault();
          if (e.shiftKey) {
            // prev
            if (searchState.matches.length) {
              searchState.current = (searchState.current - 1 + searchState.matches.length) % searchState.matches.length;
              if (searchState.mode === 'transcript') {
                applyTranscriptHighlights(searchState.matches, searchState.current);
                updateCounter();
                scrollToCurrentImmediate();
              } else {
                updateCounter();
                scrollToCurrentComment();
              }
            } else {
              runSearch({ scroll: true, notifyNoMatch: true });
            }
          } else {
            // next
            if (searchState.matches.length) {
              searchState.current = (searchState.current + 1) % searchState.matches.length;
              if (searchState.mode === 'transcript') {
                applyTranscriptHighlights(searchState.matches, searchState.current);
                updateCounter();
                scrollToCurrentImmediate();
              } else {
                updateCounter();
                scrollToCurrentComment();
              }
            } else {
              runSearch({ scroll: true, notifyNoMatch: true });
            }
          }
        } else if (e.key === 'Escape') {
          e.preventDefault();
          clearSearch();
        }
      });
    }

    if (searchPrevBtn) {
      searchPrevBtn.addEventListener('click', () => {
        updateEngagedSticky();
        if (!searchState.matches.length) {
          runSearch({ scroll: true, notifyNoMatch: true });
          return;
        }
        searchState.current = (searchState.current - 1 + searchState.matches.length) % searchState.matches.length;
        if (searchState.mode === 'transcript') {
          applyTranscriptHighlights(searchState.matches, searchState.current);
          updateCounter();
          scrollToCurrentImmediate();
        } else {
          updateCounter();
          scrollToCurrentComment();
        }
      });
    }
    if (searchNextBtn) {
      searchNextBtn.addEventListener('click', () => {
        updateEngagedSticky();
        if (!searchState.matches.length) {
          runSearch({ scroll: true, notifyNoMatch: true });
          return;
        }
        searchState.current = (searchState.current + 1) % searchState.matches.length;
        if (searchState.mode === 'transcript') {
          applyTranscriptHighlights(searchState.matches, searchState.current);
          updateCounter();
          scrollToCurrentImmediate();
        } else {
          updateCounter();
          scrollToCurrentComment();
        }
      });
    }
    // Toggle button for searching in comments
    if (searchModeToggle) {
      searchModeToggle.addEventListener('click', () => {
        const pressed = searchModeToggle.getAttribute('aria-pressed') === 'true';
        const nextPressed = !pressed;
        searchModeToggle.setAttribute('aria-pressed', String(nextPressed));
        searchState.mode = nextPressed ? 'comments' : 'transcript';
        if (!nextPressed) applyCommentFilter('');
        runSearch({ scroll: false, notifyNoMatch: false });
      });
    }

    // Global: Ctrl/Cmd+F focuses our search bar
    document.addEventListener('keydown', (e) => {
      const isMac = navigator.platform.toUpperCase().includes('MAC');
      if ((isMac ? e.metaKey : e.ctrlKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        if (searchInput) {
          searchInput.focus();
          searchInput.select();
        }
      }
      // Global Esc clears search
      if (e.key === 'Escape' && searchState.query) {
        clearSearch();
      }
    });

    // Update fixed overlay position on viewport resize
    window.addEventListener('resize', () => {
      updateFixedPosition();
    });

    // Fixed overlay fallback helpers
    let searchPlaceholder = null;
    const MIN_FIXED_WIDTH = 240;

    function measureHeaderBottom() {
      const header = document.querySelector('.admin-header');
      if (!header) return 0;
      const rect = header.getBoundingClientRect();
      return Math.max(0, rect.bottom);
    }

    function updateFixedPosition() {
      if (!searchContainer || !transcriptContainer || !searchContainer.classList.contains('fixed')) return;
      const transRect = transcriptContainer.getBoundingClientRect();
      const top = measureHeaderBottom();
      // Compute available width up to the left edge of the comment panel (if visible)
      let rightEdge = Math.min(window.innerWidth, transRect.right);
      const rightPanel = document.querySelector('.comment-panel');
      if (rightPanel) {
        const rpRect = rightPanel.getBoundingClientRect();
        if (rpRect.left > transRect.left) {
          rightEdge = Math.min(rightEdge, rpRect.left);
        }
      }
      const width = Math.max(MIN_FIXED_WIDTH, rightEdge - transRect.left - 12);
      searchContainer.style.top = `${top}px`;
      searchContainer.style.left = `${Math.max(0, transRect.left)}px`;
      searchContainer.style.width = `${width}px`;
    }

    function enableFixedSearch() {
      if (!searchContainer) return;
      // Insert placeholder to keep layout from jumping
      if (!searchPlaceholder) {
        searchPlaceholder = document.createElement('div');
        searchPlaceholder.className = 'search-placeholder';
        searchContainer.parentNode.insertBefore(searchPlaceholder, searchContainer.nextSibling);
      }
      searchPlaceholder.style.height = `${searchContainer.offsetHeight || 44}px`;
      searchContainer.classList.remove('sticky'); // avoid conflicts
      searchContainer.classList.add('fixed');
      updateFixedPosition();
    }

    function disableFixedSearch() {
      if (!searchContainer) return;
      searchContainer.classList.remove('fixed');
      searchContainer.style.top = '';
      searchContainer.style.left = '';
      searchContainer.style.width = '';
      if (searchPlaceholder) {
        searchPlaceholder.style.height = '0px';
        searchPlaceholder.remove();
        searchPlaceholder = null;
      }
    }

    function updateEngagedSticky() {
      if (!searchContainer) return;
      const hasQuery = !!(searchState.query && searchState.query.trim());
      const engaged = (document.activeElement === searchInput) || hasQuery;
      searchContainer.classList.toggle('engaged', engaged);
      if (hasQuery) {
        enableFixedSearch();
      } else {
        disableFixedSearch();
      }
    }

    function reapplySearchIfNeeded() {
      if (searchState.query && searchState.query.trim()) {
        runSearch({ scroll: false, notifyNoMatch: false });
      }
    }

    // Initialize
    editPanel.style.display = 'none';
    updateEngagedSticky();
    // After initial load, reapply search when rendering occurs via renderComments

    // Header kebab menu: toggle and export external comments
    const headerMenuBtn = document.getElementById('commentsMenuBtn');
    const headerMenu = document.getElementById('commentsActionMenu');
    const downloadExternalBtn = document.getElementById('downloadExternalBtn');

    if (headerMenuBtn && headerMenu) {
      headerMenuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = headerMenu.classList.toggle('open');
        headerMenuBtn.setAttribute('aria-expanded', String(isOpen));
      });
      // Close on outside click
      document.addEventListener('mousedown', (e) => {
        if (!headerMenu.classList.contains('open')) return;
        if (!headerMenu.contains(e.target) && e.target !== headerMenuBtn) {
          headerMenu.classList.remove('open');
          headerMenuBtn.setAttribute('aria-expanded', 'false');
        }
      });
    }

    if (downloadExternalBtn) {
      downloadExternalBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        if (headerMenu) headerMenu.classList.remove('open');
        if (headerMenuBtn) headerMenuBtn.setAttribute('aria-expanded', 'false');

        const textContent = collectExternalCommentsText();
        if (!textContent) {
          showNotification('No external comments to export.', 'error');
          return;
        }

        const defaultBase = `case-${caseId}-external-comments`;
        let suggestedName = `${defaultBase}.docx`;
        let docxBlob = null;

        try {
          const response = await API.downloadExternalComments(caseId, 'docx');
          const disposition = response.headers.get('Content-Disposition');
          const filename = parseFilenameFromDisposition(disposition);
          if (filename) {
            suggestedName = filename;
          }
          docxBlob = await response.blob();
        } catch (err) {
          if (err && err.status === 400 && String(err.message || '').toLowerCase().includes('no external comments')) {
            showNotification('No external comments to export.', 'error');
            return;
          }
          console.warn('DOCX export unavailable, falling back to TXT:', err);
          docxBlob = null;
        }

        try {
          if (docxBlob) {
            const saved = await saveExportWithPicker(suggestedName, docxBlob, textContent);
            if (!saved) {
              fallbackDownloadBlob(suggestedName, docxBlob);
              showNotification('External comments downloaded.', 'success');
            }
          } else {
            const textName = /\.docx$/i.test(suggestedName) ? suggestedName.replace(/\.docx$/i, '.txt') : `${defaultBase}.txt`;
            const savedText = await saveTextWithPicker(textName, textContent);
            if (!savedText) {
              fallbackDownload(textName, textContent);
              showNotification('External comments downloaded.', 'success');
            }
          }
        } catch (err) {
          console.error('Failed to export external comments:', err);
          showNotification('Error exporting external comments.', 'error');
        }
      });
    }

    function collectExternalCommentsText() {
      if (!Array.isArray(transcriptData) || transcriptData.length === 0) return '';
      const lines = [];
      let counter = 0;
      lines.push('External comments export');
      lines.push(`Case: ${caseId || ''}`);
      lines.push(`Generated: ${new Date().toISOString()}`);
      lines.push('');

      transcriptData.forEach((entry, entryIndex) => {
        const comments = (entry && Array.isArray(entry.comments)) ? entry.comments : [];
        if (!comments.length) return;
        // Build word list using same tokenization as UI
        const tokens = String(entry.text || '').split(/(\s+)/);
        const words = tokens.filter(t => t.trim().length > 0);
        comments.forEach((c) => {
          const ext = (c && typeof c.external_comment === 'string') ? c.external_comment.trim() : '';
          if (!ext) return;
          const s = Math.max(0, Number(c.start_word) || 0);
          const e = Math.max(s, Number(c.end_word) || s);
          const selected = words.slice(s, e + 1);
          const selectedText = selected.join(' ');
          const safeSelected = selectedText.replace(/"/g, "'");
          const safeExternal = ext.replace(/"/g, "'");
          const length = Math.max(0, e - s + 1);
          counter += 1;
          lines.push(`[${counter}] Paragraph ${entryIndex + 1}, words ${s + 1}-${e + 1} (length: ${length})`);
          lines.push(`Text: '${safeSelected}'`);
          lines.push(`External comment: '${safeExternal}'`);
          lines.push('');
        });
      });

      if (counter === 0) return '';
      return lines.join('\n');
    }

    async function saveTextWithPicker(suggestedName, text) {
      // Use File System Access API when available (Chromium browsers)
      const w = /** @type {any} */ (window);
      if (w && typeof w.showSaveFilePicker === 'function') {
        try {
          const handle = await w.showSaveFilePicker({
            suggestedName,
            types: [
              { description: 'Text Files', accept: { 'text/plain': ['.txt'] } },
            ],
          });
          const writable = await handle.createWritable();
          await writable.write(text);
          await writable.close();
          showNotification('External comments saved.', 'success');
          return true;
        } catch (err) {
          // If user cancels, just return false to avoid fallback
          if (err && (err.name === 'AbortError' || err.code === 20)) return false;
          // Other errors: fall back to download
          console.warn('showSaveFilePicker failed, falling back to download:', err);
          return false;
        }
      }
      return false;
    }

    function parseFilenameFromDisposition(disposition) {
      if (!disposition) return null;
      const utfMatch = /filename\*\=UTF-8''([^;]+)/i.exec(disposition);
      if (utfMatch && utfMatch[1]) {
        try {
          return decodeURIComponent(utfMatch[1]);
        } catch (_) {
          return utfMatch[1];
        }
      }
      const match = /filename=\"?([^\";]+)\"?/i.exec(disposition);
      if (match && match[1]) {
        return match[1];
      }
      return null;
    }

    async function saveExportWithPicker(suggestedName, docxBlob, textContent) {
      const w = /** @type {any} */ (window);
      if (w && typeof w.showSaveFilePicker === 'function') {
        try {
          const handle = await w.showSaveFilePicker({
            suggestedName,
            types: [
              { description: 'Word Document', accept: { 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] } },
              { description: 'Text File', accept: { 'text/plain': ['.txt'] } },
            ],
          });
          const writable = await handle.createWritable();
          const targetName = (handle.name || suggestedName || '').toLowerCase();
          if ((targetName.endsWith('.txt') || !docxBlob) && typeof textContent === 'string') {
            await writable.write(textContent);
          } else if (docxBlob) {
            const buffer = await docxBlob.arrayBuffer();
            await writable.write(buffer);
          } else if (typeof textContent === 'string') {
            await writable.write(textContent);
          }
          await writable.close();
          showNotification('External comments saved.', 'success');
          return true;
        } catch (err) {
          if (err && (err.name === 'AbortError' || err.code === 20)) return false;
          console.warn('showSaveFilePicker failed, falling back to download:', err);
          return false;
        }
      }
      return false;
    }

    function fallbackDownloadBlob(filename, blob) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }

    function fallbackDownload(filename, text) {
      const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      fallbackDownloadBlob(filename, blob);
    }
