function renderKaraokeWithTimings(container, transcript, alignment) {
  if (!container || !transcript || !alignment) return;
  
  const words = alignment.words || [];
  const mapped = alignment.mapped || {};
  const parts = mapped.parts || [];
  const backendPartTimes = mapped.parts_times || [];
  
  // Store words globally for highlighter access
  window.alignedWords = words;
  
  // Constants
  const MAX_LOOKAHEAD = 25;
  const TIME_TOLERANCE = 0.6; // seconds (tuned: stricter time gating to avoid large lookahead jumps)
  const MIN_GAP = 0.01; // 10ms minimum gap

  // Normalization helpers
  const norm = str => str.toLowerCase().replace(/[.,!?;:'"]/g, '').trim();
  const isAlpha = str => /^[\p{L}']+$/u.test(str);
  const isNum = str => /^[0-9][0-9.,–—-]*$/.test(str);

  // Normalized recognized words for matching
  const rnorm = words.map(w => norm(w.word));
  
  // Process transcript parts
  let tokPtr = 0; // monotonic cursor into recognized words
  let lastEnd = -MIN_GAP;

  parts.forEach((part, idx) => {
    if (!part) return;
    
    if (isAlpha(part)) {
      // Letter token processing
      const backendTime = backendPartTimes[idx];
      const partTime = backendTime?.start;
      
      // Find best match considering timing and text
      let bestMatch = -1;
      let minCost = Infinity;
      
      for (let j = tokPtr; j < Math.min(tokPtr + MAX_LOOKAHEAD, words.length); j++) {
        // Skip if timing constraint violated
        if (partTime != null) {
          const start = words[j]?.start;
          if (start != null && Math.abs(start - partTime) > TIME_TOLERANCE) continue;
        }
        
        // Calculate match cost
        const normMatch = rnorm[j] === norm(part);
        const timingCost = partTime != null && words[j]?.start != null
          ? Math.min(1, Math.abs(words[j].start - partTime) / TIME_TOLERANCE) * 0.6
          : 0;
        const distanceCost = Math.min(1, Math.max(0, j - tokPtr) / MAX_LOOKAHEAD) * 0.4;
        const cost = (normMatch ? 0 : 1) + timingCost + distanceCost;
        
        if (cost < minCost) {
          minCost = cost;
          bestMatch = j;
        }
      }

      // Create span with appropriate timing and mismatch marking
      const span = document.createElement('span');
      span.className = 'word';
      span.textContent = part;
      
      if (bestMatch >= 0) {
        const w = words[bestMatch];
        span.dataset.wordStartIndex = bestMatch;
        span.dataset.wordEndIndex = bestMatch;
        span.dataset.start = w.start;
        span.dataset.end = w.end;
        
        // Only mark mismatches for letter tokens with different normalized text
        if (norm(part) !== rnorm[bestMatch]) {
          span.classList.add('mismatch');
        }
        
        tokPtr = bestMatch + 1; // advance cursor past used word
      } else if (backendTime?.start != null && backendTime?.end != null) {
        // Fall back to backend timing
        span.dataset.start = backendTime.start;
        span.dataset.end = backendTime.end;
        tokPtr++; // still advance cursor
      } else {
        // No timing available - interpolate
        const start = lastEnd + MIN_GAP;
        const end = start + 0.3; // default duration
        span.dataset.start = start;
        span.dataset.end = end;
        tokPtr++; // advance cursor
      }
      
      // Update lastEnd for monotonicity
      const end = parseFloat(span.dataset.end);
      if (!isNaN(end)) lastEnd = end;
      
      container.appendChild(span);
      container.appendChild(document.createTextNode(' '));
      
    } else if (isNum(part)) {
      // Number token processing - never mark as mismatch
      const backendTime = backendPartTimes[idx];
      const span = document.createElement('span');
      span.className = 'word number';
      span.textContent = part;
      
      if (backendTime?.start != null && backendTime?.end != null) {
        span.dataset.start = backendTime.start;
        span.dataset.end = backendTime.end;
      } else {
        // Interpolate timing
        const start = lastEnd + MIN_GAP;
        const end = start + 0.3;
        span.dataset.start = start;
        span.dataset.end = end;
      }
      
      const end = parseFloat(span.dataset.end);
      if (!isNaN(end)) lastEnd = end;
      
      container.appendChild(span);
      container.appendChild(document.createTextNode(' '));
      tokPtr++; // always advance for numbers
    }
  });

  // Initialize karaoke highlighter
  const audio = document.getElementById('transcriptAudio');
  if (audio) {
    const highlighter = window.createKaraokeHighlighter(container, audio, words);
    if (highlighter) {
      container.dataset.highlighterId = Date.now().toString();
      window.karaokeHighlighters = window.karaokeHighlighters || new Map();
      window.karaokeHighlighters.set(container.dataset.highlighterId, highlighter);
    }
  }
}

// Export for use in dashboard.js
window.renderKaraokeWithTimings = renderKaraokeWithTimings;