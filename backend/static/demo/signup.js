        import { Auth } from './shared/auth.js';
  
        // Funkcja do wyświetlania powiadomień
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
          
          // Automatyczne usunięcie po 3 sekundach
          setTimeout(() => {
            if (notification.parentNode) {
              notification.style.opacity = '0';
              setTimeout(() => notification.remove(), 300);
            }
          }, 3000);
        }
  
        // Walidacja siły hasła
        document.getElementById('password').addEventListener('input', function() {
          const password = this.value;
          const strengthBar = document.getElementById('passwordStrength');
          let strength = 0;
          
          if (password.length > 5) strength += 25;
          if (password.match(/[a-z]+/)) strength += 25;
          if (password.match(/[A-Z]+/)) strength += 25;
          if (password.match(/[0-9]+/)) strength += 25;
          
          strengthBar.style.width = strength + '%';
          strengthBar.style.background = strength < 50 ? '#ff6b6b' : 
                                        strength < 75 ? '#ffc107' : '#4caf50';
        });
  
        document.getElementById('signupForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            const confirmPassword = document.getElementById('confirmPassword').value;
            
            // Walidacja
            if (password !== confirmPassword) {
                showNotification('Passwords do not match!');
                return;
            }
            
            if (password.length < 6) {
                showNotification('Password must be at least 6 characters');
                return;
            }
            
            try {
                // Pokazanie ładowania
                const signupBtn = document.querySelector('.signup-btn');
                signupBtn.disabled = true;
                signupBtn.textContent = 'Signing up...';
                
                const response = await fetch(`${window.location.origin}/auth/signup`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ username, password }),
                });
  
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.msg || 'Signup failed');
                }
  
                // Sukces - przekieruj do logowania z komunikatem
                showNotification('Account created successfully! Please log in.', 'success');
                setTimeout(() => {
                  window.location.href = 'login.html';
                }, 1500);
            } catch (error) {
                console.error('Signup error:', error);
                showNotification(error.message);
            } finally {
                // Przywróć przycisk
                const signupBtn = document.querySelector('.signup-btn');
                if (signupBtn) {
                  signupBtn.disabled = false;
                  signupBtn.textContent = 'Sign Up';
                }
            }
        });

