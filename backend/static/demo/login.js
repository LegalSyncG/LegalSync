      import { Auth }  from './shared/auth.js';

      function showNotification(message, type = 'error') {
          // Usuń istniejące powiadomienia
          const existing = document.querySelector('.notification');
          if (existing) existing.remove();
          
          const notification = document.createElement('div');
          notification.className = `notification ${type}`;
          notification.innerHTML = `
            <div class="icon">${type === 'error' ? '⚠️' : '✓'}</div>
            <div>${message}</div>
            <div class="close" onclick="this.parentElement.remove()">&times;</div>
          `;
          
          document.body.appendChild(notification);
          /*comment*/
          
          // Automatyczne usunięcie po 3 sekundach
          setTimeout(() => {
            if (notification.parentNode) {
              notification.style.opacity = '0';
              setTimeout(() => notification.remove(), 300);
            }
          }, 3000);
        }
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    try {
      // Pokazanie loaderka podczas logowania
      const loginBtn = document.querySelector('.login-btn');
      loginBtn.disabled = true;
      loginBtn.textContent = 'Logging in...';
      
      await Auth.login(username, password);
      // Redirect to dashboard (single demo area)
      window.location.href = '/demo/admin/dashboard.html';
    } catch (error) {
      console.error('Login error:', error);
      showNotification('Login failed. Check your credentials');
    } finally {
      const loginBtn = document.querySelector('.login-btn');
      if (loginBtn) {
        loginBtn.disabled = false;
        loginBtn.textContent = 'Login';
      }
    }
  });
