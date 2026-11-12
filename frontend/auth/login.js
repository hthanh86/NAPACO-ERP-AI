(() => {
  function safeNext(value) {
    if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\x00-\x1f]/.test(value)) return '/';
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || ['/login', '/auth/google/start', '/auth/google/callback'].includes(url.pathname)) return '/';
    return url.pathname + url.search + url.hash;
  }
  const next = safeNext(new URLSearchParams(location.search).get('next'));
  document.getElementById('googleLogin').href = '/auth/google/start?next=' + encodeURIComponent(next);
  document.getElementById('login').onsubmit = async event => {
    event.preventDefault();
    const form = event.target, button = form.querySelector('button'), errorBox = document.getElementById('error');
    button.disabled = true; button.textContent = 'Đang đăng nhập…'; errorBox.textContent = '';
    try {
      const response = await fetch('/api/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.fromEntries(new FormData(form)))});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Không đăng nhập được. Vui lòng thử lại.');
      location.assign(next);
    } catch (error) { errorBox.textContent = error.message; button.disabled = false; button.textContent = 'Đăng nhập'; }
  };
})();
