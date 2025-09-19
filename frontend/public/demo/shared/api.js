class LegalSyncAPI {
        constructor() {
            // Use current origin to avoid hardcoded ports/hosts
            this.baseUrl = window.location.origin;
        }

    async fetchProtected(url, options = {}) {
        const path = url.startsWith('/') ? url : `/${url}`;
        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
        };

        const response = await fetch(this.baseUrl + path, {
            ...options,
            headers,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || errorData.message || 'Request failed');
        }

        return response.json();
    }

    async createCase({ name, audioFile, transcriptFile, transcriptText }) {
        const form = new FormData();
        if (name) form.append('name', name);
        if (audioFile) form.append('audio', audioFile);
        if (transcriptFile) form.append('transcript', transcriptFile);
        if (transcriptText) form.append('transcript_text', transcriptText);

        const response = await fetch(this.baseUrl + '/cases', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            },
            body: form,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || 'Failed to create case');
        }
        return response.json();
    }

    async getCaseAlignment(caseId) {
        const response = await fetch(this.baseUrl + `/cases/${caseId}/alignment`, {
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async getCaseStatus(caseId) {
        const response = await fetch(this.baseUrl + `/cases/${caseId}/status`, {
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            },
        });
        if (!response.ok) return { status: 'unknown' };
        return response.json();
    }

    async getCaseTranscript(caseId) {
        const response = await fetch(this.baseUrl + `/cases/${caseId}/transcript`, {
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            },
        });
        if (!response.ok) return null;
        return response.json();
    }

    async deleteCase(caseId) {
        const response = await fetch(this.baseUrl + `/cases/${caseId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            },
        });
        if (!response.ok) {
            const err = await response.json().catch(()=>({}));
            throw new Error(err.error || 'Failed to delete case');
        }
        return response.json();
    }

    async renameCase(caseId, name) {
        const response = await fetch(this.baseUrl + `/cases/${caseId}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name })
        });
        if (!response.ok) {
            const err = await response.json().catch(()=>({}));
            throw new Error(err.error || 'Failed to rename case');
        }
        return response.json();
    }

    async postProtected(url, options = {}) {
        const path = url.startsWith('/') ? url : `/${url}`;
        const headers = {
            'Authorization': `Bearer ${sessionStorage.getItem('legalSyncToken')}`,
            'Content-Type': 'application/json',
            ...options.headers,
        };

        const response = await fetch(this.baseUrl + path, {
            method: 'PATCH',
            ...options,
            headers,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || errorData.message || 'Request failed');
        }

        return response.json();
    }


    async uploadFiles(audioFile, transcriptFile) {
        const formData = new FormData();
        formData.append('audio', audioFile);
        formData.append('transcript', transcriptFile);

        const response = await fetch(`${this.baseUrl}/documents/upload`, {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });
        
        return response.json();
    }

    async getTranscript(id) {
        const response = await fetch(`${this.baseUrl}/documents/${id}`);
        return response.json();
    }

    async saveComments(comments) {
        const response = await fetch(`${this.baseUrl}/comments/batch`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ comments }),
            credentials: 'include'
        });
        
        return response.json();
    }

    async submitTranscript(id) {
        const response = await fetch(`${this.baseUrl}/documents/${id}/submit`, {
            method: 'POST',
            credentials: 'include'
        });
        
        return response.json();
    }
}

export const API = new LegalSyncAPI();
