export class AudioPlayer {
    constructor(audioElement, transcriptContainer) {
        this.audio = audioElement;
        this.transcript = transcriptContainer;
        this.words = [];
        
        this.initEvents();
    }

    initEvents() {
        this.audio.addEventListener('timeupdate', this.highlightCurrentWord.bind(this));
    }

    loadTranscript(words) {
        this.words = words;
        this.renderTranscript();
    }

    renderTranscript() {
        this.transcript.innerHTML = '';
        
        this.words.forEach((word, index) => {
            const wordEl = document.createElement('span');
            wordEl.className = 'word';
            wordEl.textContent = word.word + ' ';
            wordEl.dataset.index = index;
            wordEl.dataset.start = word.start;
            wordEl.dataset.end = word.end;
            
            wordEl.addEventListener('click', () => {
                this.audio.currentTime = word.start;
            });
            
            this.transcript.appendChild(wordEl);
        });
    }

    highlightCurrentWord() {
        const currentTime = this.audio.currentTime;
        
        this.transcript.querySelectorAll('.word').forEach(wordEl => {
            const start = parseFloat(wordEl.dataset.start);
            const end = parseFloat(wordEl.dataset.end);
            
            if (currentTime >= start && currentTime <= end) {
                wordEl.classList.add('active');
                wordEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } else {
                wordEl.classList.remove('active');
            }
        });
    }
}