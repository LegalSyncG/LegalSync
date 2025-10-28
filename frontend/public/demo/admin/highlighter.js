// Robust karaoke highlighter implementation
class KaraokeHighlighter {
  // alignedWords: optional array of recognized words (from alignment.words)
  constructor(container, audio, alignedWords) {
    // If a previous highlighter was attached to this container, detach it first
    try {
      if (container && container._karaokeHighlighter && typeof container._karaokeHighlighter.detach === 'function') {
        container._karaokeHighlighter.detach();
      }
    } catch (e) {
      // ignore
    }

    this.container = container;
    this.audio = audio;
    // span elements rendered in the container
    this.words = Array.from(container.getElementsByClassName('word'));
    this.alignedWords = Array.isArray(alignedWords) ? alignedWords : (window.alignedWords || []);
    this.lastActive = null;
    this.timeRanges = [];
    this.boundUpdateHighlight = this.updateHighlight.bind(this);
    // store pointer on container so subsequent renders can detach previous instance
    if (container) container._karaokeHighlighter = this;
    this.initialize();
  }

  initialize() {
    this.computeTimeRanges();
    this.attachListeners();
  }

  computeTimeRanges() {
    this.timeRanges = [];
    const epsilon = 0.01; // 10ms minimum gap
    let lastEnd = -epsilon;

    this.words.forEach((word, idx) => {
      // Get word timing
      let start = parseFloat(word.dataset.start);
      let end = parseFloat(word.dataset.end);
      const startIdx = parseInt(word.dataset.wordStartIndex);
      const endIdx = parseInt(word.dataset.wordEndIndex);

      // If we have indices but missing times, try to compute from provided alignedWords
      if (!isNaN(startIdx) && !isNaN(endIdx) && (isNaN(start) || isNaN(end))) {
        if (this.alignedWords && this.alignedWords.length) {
          const wordSlice = this.alignedWords.slice(startIdx, endIdx + 1)
            .filter(w => w && w.start != null && w.end != null);

          if (wordSlice.length > 0) {
            start = Math.min(...wordSlice.map(w => w.start));
            end = Math.max(...wordSlice.map(w => w.end));
          }
        }
      }

      // If still no timing, interpolate
      if (isNaN(start) || isNaN(end)) {
        // Look ahead for next known timing
        let nextStart = null;
        for (let j = idx + 1; j < this.words.length && nextStart == null; j++) {
          const ns = parseFloat(this.words[j].dataset.start);
          if (!isNaN(ns)) nextStart = ns;
        }

        // Interpolate or use default duration
        if (nextStart != null) {
          start = lastEnd + epsilon;
          end = Math.min(nextStart - epsilon, start + 1.0);
        } else {
          start = lastEnd + epsilon;
          end = start + 0.3; // default duration
        }
      }

      // Ensure monotonicity and minimum gap
      start = Math.max(start, lastEnd + epsilon);
      end = Math.max(end, start + epsilon);

      // Store computed range
      this.timeRanges.push({
        start,
        end,
        word,
        index: idx
      });

      lastEnd = end;
    });
  }

  findCurrentIndex(time) {
    // Binary search for efficiency
    let left = 0;
    let right = this.timeRanges.length - 1;

    while (left <= right) {
      const mid = Math.floor((left + right) / 2);
      const range = this.timeRanges[mid];

      if (time >= range.start && time <= range.end) {
        return mid;
      } else if (time < range.start) {
        right = mid - 1;
      } else {
        left = mid + 1;
      }
    }

    // If we're between words, return the next word if it's close enough
    if (left < this.timeRanges.length && 
        time > this.timeRanges[left].start - 0.1) {
      return left;
    }

    return -1;
  }

  updateHighlight() {
    const time = this.audio.currentTime;
    const idx = this.findCurrentIndex(time);

    // Clear previous highlight if needed
    if (this.lastActive && (idx < 0 || this.timeRanges[idx].word !== this.lastActive)) {
      this.lastActive.classList.remove('active');
      this.lastActive = null;
    }

    // Apply new highlight
    if (idx >= 0) {
      const wordElem = this.timeRanges[idx].word;
      if (this.lastActive !== wordElem) {
        // Keep compatibility with existing CSS which uses .highlighted
        wordElem.classList.add('highlighted');
        // also add legacy 'active' for any code expecting it
        wordElem.classList.add('active');
        this.lastActive = wordElem;

        // Ensure word is visible in viewport
        const containerRect = this.container.getBoundingClientRect();
        const wordRect = wordElem.getBoundingClientRect();

        if (wordRect.top < containerRect.top || wordRect.bottom > containerRect.bottom) {
          wordElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  }

  attachListeners() {
    this.audio.addEventListener('timeupdate', this.boundUpdateHighlight);
    this.audio.addEventListener('seeking', this.boundUpdateHighlight);
  }

  detach() {
    this.audio.removeEventListener('timeupdate', this.boundUpdateHighlight);
    this.audio.removeEventListener('seeking', this.boundUpdateHighlight);
    if (this.lastActive) {
      this.lastActive.classList.remove('active');
      this.lastActive.classList.remove('highlighted');
      this.lastActive = null;
    }
    try {
      if (this.container && this.container._karaokeHighlighter === this) {
        delete this.container._karaokeHighlighter;
      }
    } catch (e) {}
  }
}

// Function to create highlighter instance
function createKaraokeHighlighter(container, audio) {
  if (!container || !audio) return null;
  // Try to pick up alignedWords from window if provided
  const alignedWords = window.alignedWords || null;
  return new KaraokeHighlighter(container, audio, alignedWords);
}

// Export for use in other files
window.KaraokeHighlighter = KaraokeHighlighter;
window.createKaraokeHighlighter = createKaraokeHighlighter;