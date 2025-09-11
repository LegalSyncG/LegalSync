class AuthService {
  constructor() {
    this.token = null;
    this.user = null;
  }

async login(username, password) {
  try {
    const response = await fetch(`${window.location.origin}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Login failed');
    }

    const data = await response.json();
    this.token = data.token; 
    
    this.user = { 
      username, 
      role: 'admin'
    };

    sessionStorage.setItem('legalSyncToken', data.token);
    sessionStorage.setItem('legalSyncUser', JSON.stringify(this.user));
    
    return this.user;
  } catch (error) {
    console.error('Login error:', error);
    throw error;
  }
}


  async logout() {
    sessionStorage.removeItem('legalSyncUser');
    sessionStorage.removeItem('legalSyncToken');
    window.location.href = '../login.html';
  }

  getCurrentUser() {
    if (!this.user) {
      const storedUser = sessionStorage.getItem('legalSyncUser');
      if (storedUser) {
        this.user = JSON.parse(storedUser);
        this.token = sessionStorage.getItem('legalSyncToken');
      }
    }
    return this.user;
  }

  isAuthenticated() {
    return this.getCurrentUser() !== null;
  }
}

export const Auth = new AuthService();
