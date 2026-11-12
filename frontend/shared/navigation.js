/* Shared navigation for native screens and the existing ERP shell. */
(() => {
  window.NAPACO_IDENTITY = fetch('/api/me', {cache:'no-store'}).then(async response => {
    if (response.status === 401) {
      location.assign('/login?next=' + encodeURIComponent(location.pathname + location.search));
      throw Error('Vui lòng đăng nhập.');
    }
    if (!response.ok) throw Error('Không đọc được tài khoản.');
    return response.json();
  });
  function el(tag, text, className) {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function link(label, href, icon) {
    const item = el('a', '', 'erp-module-link'); item.href = href;
    const mark = el('span', icon, 'erp-module-icon'); mark.setAttribute('aria-hidden', 'true');
    item.append(mark, el('span', label));
    const current = location.pathname === '/users' || location.pathname.startsWith('/master/')
      ? location.pathname : '/?view=' + (new URLSearchParams(location.search).get('view') || 'index');
    if (href === current) item.setAttribute('aria-current', 'page');
    return item;
  }
  function group(title, entries) {
    const section = el('div', '', 'erp-nav-group');
    section.append(el('div', title, 'erp-nav-label'));
    entries.forEach(entry => section.append(link(...entry)));
    return section;
  }
  async function init() {
    let sidebar = document.getElementById('erpSidebar');
    if (!sidebar) {
      document.body.classList.add('erp-native-shell');
      const content = el('div', '', 'erp-native-content');
      for (const child of [...document.body.children]) {
        if (!['SCRIPT', 'STYLE', 'DIALOG'].includes(child.tagName)) content.append(child);
      }
      sidebar = el('aside', '', 'erp-sidebar erp-client-sidebar'); sidebar.id = 'erpSidebar';
      const top = el('div', '', 'erp-sidebar-top');
      const brand = el('a', 'NAPACO ERP', 'erp-brand-name'); brand.href = '/?view=index';
      const toggle = el('button', '☰ Menu', 'erp-menu-toggle'); toggle.type = 'button';
      toggle.setAttribute('aria-controls', 'erpModuleMenu'); toggle.setAttribute('aria-expanded', 'false');
      toggle.onclick = () => toggle.setAttribute('aria-expanded', String(sidebar.toggleAttribute('data-menu-open')));
      sidebar.onkeydown = event => {if(event.key === 'Escape') {sidebar.removeAttribute('data-menu-open');toggle.setAttribute('aria-expanded','false');toggle.focus();}};
      top.append(brand, toggle); sidebar.append(top);
      const nav = el('nav', '', 'erp-module-menu'); nav.id = 'erpModuleMenu'; nav.setAttribute('aria-label', 'Phân hệ');
      nav.append(group('Đơn hàng', [['Tổng quan','/?view=index','▦'],['Tạo đơn hàng','/?view=create','+'],['Định Hình','/?view=list','◫'],['Bế','/?view=be','✂']]),
        group('Nguyên Liệu', [['Tạo Đơn','/?view=film-create','+'],['Màng Đã Đặt','/?view=film','▤'],['Nhận Màng','/?view=film-receive','↓'],['Tồn Kho','/?view=film-stock','▥']]));
      sidebar.append(nav); document.body.prepend(sidebar, content);
    }
    const nav = document.getElementById('erpModuleMenu');
    const master = group('Dữ Liệu Master', [['Khách Hàng','/master/customers','♙'],['Sản Phẩm','/master/products','▧'],['Nhà Cung Cấp','/master/suppliers','▣']]);
    master.id = 'erpMasterMenu'; (nav || sidebar).prepend(master);
    const panel = el('section', '', 'erp-account-panel'); sidebar.append(panel);
    try {
      const user = await window.NAPACO_IDENTITY;
      window.NAPACO_USER = user;
      if (user.permissions.includes('USER_MANAGE')) {
        master.insertBefore(link('User', '/users', '⚙'), master.children[1]);
      }
      panel.append(el('strong', user.name), el('span', user.email || user.id), el('span', user.google_connected ? 'Google Drive: đã kết nối' : 'Google Drive: chưa kết nối'));
      const google = el('a', user.google_connected ? 'Đổi tài khoản Google' : 'Kết nối Google Drive');
      google.href = '/auth/google/start?next=' + encodeURIComponent(location.pathname + location.search); panel.append(google);
      const logout = el('button', 'Đăng xuất'); logout.type = 'button'; panel.append(logout);
      logout.onclick = async () => {
        logout.disabled = true;
        try {const result = await fetch('/api/logout', {method:'POST'}); if(!result.ok) throw Error('Không đăng xuất được.'); location.assign('/login');}
        catch(error) {logout.disabled = false; panel.append(el('span', error.message));}
      };
    } catch (error) {panel.textContent = error.message;}
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
