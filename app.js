'use strict';
(() => {
  const $app = document.getElementById('app');
  const $overlay = document.getElementById('overlay-root');
  const $toast = document.getElementById('toast');
  const state = { user: null, lockMinutes: 10, tab: 'students' };
  let lastActivity = Date.now();
  let lastPing = 0;
  let toastTimer = null;
  let seq = 0;

  const MEMO_WARNING = '[주의] 이 메모는 담당 강사를 포함한 모든 사용자에게 보입니다. '
    + '가정 사정(이혼·질병·경제 상황 등), 주민등록번호, 계좌 정보 등 민감한 내용은 입력하지 마십시오. '
    + '연락·응대 시 필요한 최소한의 업무 정보만 기재해 주십시오.';
  const STATUSES = ['수강중', '휴원', '종료'];

  // ------------------------------------------------------------------ 기본 도구
  class ApiError extends Error {
    constructor(message, status, code) { super(message); this.status = status; this.code = code; }
  }

  async function api(method, path, body) {
    const options = { method, credentials: 'same-origin', cache: 'no-store', headers: { 'X-Requested-With': 'academy' } };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, options);
    } catch (e) {
      throw new ApiError('서버에 연결할 수 없습니다. 프로그램(검은 콘솔 창)이 실행 중인지 확인하십시오.', 0, 'network');
    }
    let data = {};
    try { data = await res.json(); } catch (e) { /* 본문 없음 */ }
    if (!res.ok) {
      if (res.status === 401 && data.code === 'login') sessionExpired();
      throw new ApiError(data.error || '처리하지 못했습니다.', res.status, data.code || '');
    }
    return data;
  }

  // 모든 화면 값은 textContent(createTextNode)로만 넣는다. innerHTML 은 사용하지 않는다.
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    let value;
    for (const [key, val] of Object.entries(props || {})) {
      if (val === null || val === undefined || val === false) continue;
      if (key === 'class') el.className = val;
      else if (key === 'value') value = val;
      else if (key === 'checked') el.checked = true;
      else if (key.startsWith('on') && typeof val === 'function') el.addEventListener(key.slice(2), val);
      else el.setAttribute(key, val === true ? '' : String(val));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    if (value !== undefined) el.value = value;
    return el;
  }

  function toast(message, isError) {
    $toast.textContent = message;
    $toast.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $toast.className = 'toast'; }, 3000);
  }

  function guard(fn) {
    return async (...args) => {
      try {
        await fn(...args);
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.code !== 'login') toast(err.message, true);
        } else {
          console.error(err);
          toast('오류가 발생했습니다.', true);
        }
      }
    };
  }

  const safeGet = (key) => { try { return localStorage.getItem(key); } catch (e) { return null; } };
  const safeSet = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* 무시 */ } };
  const fmtMoney = (n) => Number(n).toLocaleString('ko-KR') + '원';

  const btn = (text, onclick, cls) => h('button', { type: 'button', class: ('btn ' + (cls || '')).trim(), onclick }, text);
  const card = (title, ...body) => h('section', { class: 'card' }, h('h3', {}, title), body);
  const actions = (...items) => h('div', { class: 'actions' }, items);
  const kv = (rows) => h('dl', { class: 'kv' }, rows.filter(Boolean).map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));

  function table(headers, rows, emptyText) {
    const body = rows.length
      ? rows.map((cells) => h('tr', {}, cells.map((c) => h('td', {}, c))))
      : [h('tr', {}, h('td', { colspan: headers.length, class: 'muted' }, emptyText || '내역이 없습니다.'))];
    return h('div', { class: 'table-wrap' }, h('table', { class: 'tbl' },
      h('thead', {}, h('tr', {}, headers.map((t) => h('th', {}, t)))), h('tbody', {}, body)));
  }

  // ------------------------------------------------------------------ 대화상자
  function closeModals() { $overlay.replaceChildren(); }

  function fieldEl(spec, initial, inputs) {
    const id = 'f' + (++seq);
    const kind = spec.kind || 'text';
    const val = initial[spec.key] === undefined || initial[spec.key] === null ? '' : initial[spec.key];
    let input;
    if (kind === 'select') {
      input = h('select', { id, value: String(val) },
        (spec.options || []).map((o) => h('option', { value: String(o.value) }, o.label)));
      // 초기값이 목록에 없으면 브라우저는 아무것도 선택하지 않으므로 첫 항목을 선택해 둔다.
      if (input.options.length && ![...input.options].some((o) => o.value === String(val))) input.selectedIndex = 0;
    } else if (kind === 'textarea') {
      input = h('textarea', { id, rows: spec.rows || 4, maxlength: spec.maxlength, value: String(val) });
    } else if (kind === 'checkbox') {
      input = h('input', { id, type: 'checkbox', checked: !!val });
    } else {
      input = h('input', { id, type: kind, value: String(val), maxlength: spec.maxlength, inputmode: spec.inputmode, placeholder: spec.placeholder });
    }
    inputs[spec.key] = input;
    if (kind === 'checkbox') {
      return h('div', { class: 'field' }, h('label', { class: 'check', for: id }, input, spec.text || spec.label),
        spec.hint && h('div', { class: 'hint' }, spec.hint));
    }
    return h('div', { class: 'field' }, h('label', { for: id }, spec.label), input, spec.hint && h('div', { class: 'hint' }, spec.hint));
  }

  function readValues(inputs) {
    const values = {};
    for (const [key, el] of Object.entries(inputs)) values[key] = el.type === 'checkbox' ? el.checked : el.value;
    return values;
  }

  function formModal({ title, intro, fields, initial, submitText, onSubmit }) {
    return new Promise((resolve) => {
      const inputs = {};
      const errorBox = h('div', { class: 'form-error', role: 'alert' });
      const submitBtn = h('button', { type: 'submit', class: 'btn primary' }, submitText || '확인');
      const form = h('form', { autocomplete: 'off', novalidate: true },
        intro && h('p', { class: 'intro' }, intro),
        fields.map((spec) => fieldEl(spec, initial || {}, inputs)),
        errorBox,
        h('div', { class: 'buttons' }, h('button', { type: 'button', class: 'btn', onclick: () => finish(null) }, '취소'), submitBtn));
      const overlay = h('div', { class: 'overlay' },
        h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, h('h2', {}, title), form));
      function finish(result) { overlay.remove(); resolve(result); }
      overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') finish(null); });
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorBox.textContent = '';
        submitBtn.disabled = true;
        try {
          const result = await onSubmit(readValues(inputs));
          finish(result === undefined ? true : result);
        } catch (err) {
          if (err instanceof ApiError) errorBox.textContent = err.message;
          else { console.error(err); errorBox.textContent = '오류가 발생했습니다.'; }
          submitBtn.disabled = false;
        }
      });
      $overlay.append(overlay);
      const first = form.querySelector('input:not([type=checkbox]), select, textarea');
      if (first) first.focus();
    });
  }

  function confirmModal(message, okText) {
    return new Promise((resolve) => {
      const done = (answer) => { overlay.remove(); resolve(answer); };
      const overlay = h('div', { class: 'overlay' }, h('div', { class: 'modal', role: 'alertdialog', 'aria-modal': 'true' },
        h('p', { class: 'intro' }, message),
        h('div', { class: 'buttons' }, btn('취소', () => done(false)), btn(okText || '확인', () => done(true), 'primary'))));
      overlay.addEventListener('keydown', (e) => { if (e.key === 'Escape') done(false); });
      $overlay.append(overlay);
      overlay.querySelector('.primary').focus();
    });
  }

  // ------------------------------------------------------------------ 로그인 / 잠금
  function sessionExpired() {
    if (!state.user) return;
    state.user = null;
    showLogin('자동 잠금 또는 세션 만료로 로그아웃되었습니다. 다시 로그인하십시오.');
  }

  async function showLogin(message) {
    state.user = null;
    closeModals();
    $app.replaceChildren();
    let s;
    try {
      s = await api('GET', '/api/state');
    } catch (e) {
      $app.append(h('p', { class: 'fatal' }, e.message));
      return;
    }
    state.lockMinutes = s.lock_minutes;
    if (!s.has_users) { renderSetup(); return; }
    const { users } = await api('GET', '/api/login-users');
    renderLogin(users, message);
  }

  function loginShell(lead, ...body) {
    return h('div', { class: 'center-wrap' }, h('div', { class: 'login-card' },
      h('h1', {}, '학원 학생 관리'), h('p', { class: 'lead' }, lead), body));
  }

  function renderLogin(users, message) {
    const msg = h('div', { class: 'form-msg', role: 'alert' }, message || '');
    const select = h('select', { id: 'login-user' }, users.map((u) => h('option', { value: u.id }, `${u.name} (${u.role})`)));
    const last = safeGet('academyLastUser');
    if (last && users.some((u) => String(u.id) === last)) select.value = last;
    const pin = h('input', { id: 'login-pin', type: 'password', inputmode: 'numeric', maxlength: 6, autocomplete: 'off' });
    const form = h('form', { novalidate: true },
      h('div', { class: 'field' }, h('label', { for: 'login-user' }, '사용자'), select),
      h('div', { class: 'field' }, h('label', { for: 'login-pin' }, 'PIN'), pin),
      h('button', { type: 'submit', class: 'btn primary' }, '로그인'), msg);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      msg.textContent = '';
      try {
        const res = await api('POST', '/api/login', { user_id: select.value, pin: pin.value });
        safeSet('academyLastUser', select.value);
        state.user = res.user;
        state.tab = 'students';
        markActivity();
        renderApp();
      } catch (err) {
        if (!(err instanceof ApiError)) throw err;
        msg.textContent = err.message;
        pin.value = '';
        pin.focus();
      }
    });
    $app.replaceChildren(loginShell('사용자를 선택하고 PIN을 입력하십시오.', form));
    pin.focus();
  }

  function renderSetup() {
    const msg = h('div', { class: 'form-msg', role: 'alert' });
    const inputs = {};
    const fields = [
      { key: 'name', label: '이름', maxlength: 30 },
      { key: 'pin', label: 'PIN (숫자 4~6자리)', kind: 'password', inputmode: 'numeric', maxlength: 6 },
      { key: 'pin2', label: 'PIN 확인', kind: 'password', inputmode: 'numeric', maxlength: 6 },
    ];
    const form = h('form', { novalidate: true }, fields.map((f) => fieldEl(f, { name: '원장' }, inputs)),
      h('button', { type: 'submit', class: 'btn primary' }, '원장 계정 만들기'), msg);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      msg.textContent = '';
      try {
        const res = await api('POST', '/api/setup', readValues(inputs));
        state.user = res.user;
        state.tab = 'students';
        markActivity();
        renderApp();
      } catch (err) {
        if (!(err instanceof ApiError)) throw err;
        msg.textContent = err.message;
      }
    });
    $app.replaceChildren(loginShell('최초 실행입니다. 원장 계정을 만드십시오.', form));
  }

  async function endSession(kind, message) {
    state.user = null;
    try { await api('POST', kind === 'lock' ? '/api/lock' : '/api/logout'); } catch (e) { /* 무시 */ }
    await showLogin(message);
  }

  async function quit() {
    if (!(await confirmModal('프로그램을 종료하시겠습니까?\n종료하면 이 화면도 사용할 수 없게 됩니다.', '종료'))) return;
    await api('POST', '/api/shutdown');
    state.user = null;
    closeModals();
    $app.replaceChildren(h('div', { class: 'center-wrap' }, h('div', { class: 'login-card' },
      h('h1', {}, '종료되었습니다'), h('p', { class: 'lead' }, '이 창은 닫으셔도 됩니다.'))));
  }

  // 무입력 자동 잠금: 서버 세션도 같은 시간이 지나면 만료된다.
  function markActivity() {
    lastActivity = Date.now();
    if (state.user && lastActivity - lastPing > 20000) {
      lastPing = lastActivity;
      api('POST', '/api/ping').catch(() => {});
    }
  }
  ['keydown', 'mousedown', 'mousemove', 'touchstart', 'wheel'].forEach((name) =>
    document.addEventListener(name, markActivity, { passive: true }));
  setInterval(() => {
    if (state.user && Date.now() - lastActivity > state.lockMinutes * 60000) {
      endSession('lock', '자동 잠금되었습니다. 다시 로그인하십시오.');
    }
  }, 1000);

  // ------------------------------------------------------------------ 메인 화면
  const TABS = [
    { id: 'students', label: '학생', view: viewStudents },
    { id: 'families', label: '가족', view: viewFamilies },
    { id: 'classes', label: '수업·특강', view: viewClasses, director: true },
    { id: 'users', label: '사용자', view: viewUsers, director: true },
    { id: 'settings', label: '설정', view: viewSettings, director: true },
  ];

  function renderApp() {
    closeModals();
    const user = state.user;
    const tabs = TABS.filter((t) => !t.director || user.is_director);
    if (!tabs.some((t) => t.id === state.tab)) state.tab = 'students';
    const content = h('main', { class: 'content' });
    const buttons = {};
    const nav = h('nav', { class: 'tabs', role: 'tablist' }, tabs.map((t) => {
      buttons[t.id] = h('button', { type: 'button', role: 'tab', class: 'tab', onclick: () => show(t.id) }, t.label);
      return buttons[t.id];
    }));
    function show(id) {
      state.tab = id;
      tabs.forEach((t) => { buttons[t.id].className = 'tab' + (t.id === id ? ' active' : ''); });
      content.replaceChildren();
      tabs.find((t) => t.id === id).view(content);
    }
    const header = h('header', { class: 'topbar' },
      h('h1', {}, '학원 학생 관리'), h('div', { class: 'spacer' }),
      h('span', { class: 'who' }, `사용자: ${user.name} (${user.role})`),
      btn('잠금', () => endSession('lock', '잠금되었습니다. 다시 로그인하십시오.')),
      btn('로그아웃', () => endSession('logout', '')),
      user.is_director && btn('프로그램 종료', guard(quit), 'danger'));
    $app.replaceChildren(header, nav, content);
    show(state.tab);
  }

  // ------------------------------------------------------------------ 학생
  function viewStudents(root) {
    const dir = state.user.is_director;
    let sid = null;
    let query = '';
    let timer = null;
    let cur = null;
    const listEl = h('ul', { class: 'list' });
    const detailEl = h('div', {});
    const search = h('input', {
      type: 'search', class: 'search', placeholder: '이름 검색', 'aria-label': '이름 검색',
      oninput: (e) => {
        clearTimeout(timer);
        timer = setTimeout(guard(async () => { query = e.target.value.trim(); await loadList(); }), 250);
      },
    });

    async function loadList() {
      const { students } = await api('GET', '/api/students?q=' + encodeURIComponent(query));
      listEl.replaceChildren(...(students.length
        ? students.map((s) => h('li', { class: s.id === sid ? 'active' : '' },
          h('button', { type: 'button', onclick: guard(() => select(s.id)) }, h('span', {}, s.name), h('span', { class: 'muted' }, s.grade))))
        : [h('li', { class: 'empty' }, '학생이 없습니다.')]));
    }

    async function select(id) { sid = id; await Promise.all([loadList(), loadDetail()]); }

    async function loadDetail() {
      if (sid === null) {
        cur = null;
        detailEl.replaceChildren(h('p', { class: 'empty' }, '왼쪽 목록에서 학생을 선택하십시오.'));
        return;
      }
      const d = await api('GET', `/api/students/${sid}`);
      cur = d;
      const s = d.student;
      const rows = d.enrollments.map((e) => {
        const cells = [e.class_name, e.class_type, h('span', { class: 'badge' }, e.status), e.status_changed_at,
          e.effective_status !== e.status ? h('span', { class: 'badge alert' }, '특강 기간 종료 → 종료로 간주') : ''];
        if (dir) {
          cells.push(h('div', { class: 'row-actions' },
            btn('상태 변경', guard(() => changeStatus(e)), 'small'), btn('취소', guard(() => removeEnrollment(e)), 'small danger')));
        }
        return cells;
      });
      detailEl.replaceChildren(
        card('수업정보 (전체 공개)', kv([['이름', s.name], ['학년', s.grade || '-'], dir && ['가족', d.family_name || '-']]),
          dir && actions(btn('수정', guard(editStudent)), btn('학생 삭제', guard(deleteStudent), 'danger'))),
        card('개인정보 (원장·담당 강사)',
          d.private
            ? kv([['연락처', d.private.phone || '-'], ['주소', d.private.address || '-'], ['학교', d.private.school || '-']])
            : h('p', { class: 'warn' }, d.private_error),
          dir && actions(btn('수정', guard(editPrivate)))),
        card('수강 내역', table(['수업', '유형', '상태', '상태 변경일', '비고'].concat(dir ? [''] : []), rows),
          dir && actions(btn('수강 등록', guard(enroll)))));
    }

    async function familyOptions() {
      const { families } = await api('GET', '/api/families');
      return [{ value: '', label: '(없음)' }].concat(families.map((f) => ({ value: f.id, label: `${f.name} (#${f.id})` })));
    }
    const studentFields = (options) => [
      { key: 'name', label: '이름', maxlength: 100 },
      { key: 'grade', label: '학년', maxlength: 20, hint: '예: 초5, 중1' },
      { key: 'family_id', label: '가족', kind: 'select', options },
    ];

    async function addStudent() {
      const options = await familyOptions();
      const id = await formModal({
        title: '학생 추가', fields: studentFields(options), initial: { family_id: '' },
        onSubmit: async (v) => (await api('POST', '/api/students', v)).id,
      });
      if (id) { query = ''; search.value = ''; await select(id); }
    }

    async function editStudent() {
      const options = await familyOptions();
      const s = cur.student;
      const ok = await formModal({
        title: '학생 수정', fields: studentFields(options),
        initial: { name: s.name, grade: s.grade, family_id: s.family_id },
        onSubmit: (v) => api('PUT', `/api/students/${s.id}`, v),
      });
      if (ok) await select(s.id);
    }

    async function deleteStudent() {
      if (!(await confirmModal('선택한 학생을 삭제하시겠습니까?\n(개인정보도 함께 삭제됩니다)', '삭제'))) return;
      await api('DELETE', `/api/students/${sid}`);
      sid = null;
      await Promise.all([loadList(), loadDetail()]);
    }

    async function editPrivate() {
      const ok = await formModal({
        title: '개인정보 수정',
        fields: [{ key: 'phone', label: '연락처', maxlength: 30 }, { key: 'address', label: '주소', maxlength: 200 },
          { key: 'school', label: '학교', maxlength: 60 }],
        initial: cur.private || {},
        onSubmit: (v) => api('PUT', `/api/students/${sid}/private`, v),
      });
      if (ok) await loadDetail();
    }

    async function enroll() {
      const { classes } = await api('GET', '/api/classes');
      if (!classes.length) { toast("먼저 '수업·특강' 탭에서 수업을 등록하십시오.", true); return; }
      const ok = await formModal({
        title: '수강 등록',
        fields: [{ key: 'class_id', label: '수업', kind: 'select', options: classes.map((c) => ({ value: c.id, label: `${c.name} [${c.type}]` })) },
          { key: 'start_date', label: '시작일', kind: 'date' }],
        initial: { start_date: new Date().toLocaleDateString('sv-SE') },
        onSubmit: (v) => api('POST', `/api/students/${sid}/enrollments`, v),
      });
      if (ok) await loadDetail();
    }

    async function changeStatus(e) {
      const ok = await formModal({
        title: `수강 상태 변경 - ${e.class_name}`,
        fields: [{ key: 'status', label: '상태', kind: 'select', options: STATUSES.map((v) => ({ value: v, label: v })) },
          { key: 'date', label: '변경일', kind: 'date', hint: '휴원·종료일 또는 복귀일. 수강중으로 복귀하면 열람 유예 기간이 초기화됩니다.' }],
        initial: { status: e.status, date: new Date().toLocaleDateString('sv-SE') },
        onSubmit: (v) => api('PUT', `/api/enrollments/${e.id}`, v),
      });
      if (ok) await loadDetail();
    }

    async function removeEnrollment(e) {
      if (!(await confirmModal(`'${e.class_name}' 수강 등록을 취소(삭제)하시겠습니까?\n상태를 '종료'로 바꾸는 것과 달리 이력이 남지 않습니다.`, '삭제'))) return;
      await api('DELETE', `/api/enrollments/${e.id}`);
      await loadDetail();
    }

    root.append(h('div', { class: 'split' },
      h('aside', { class: 'sidebar' }, h('div', { class: 'tools' }, search, dir && btn('추가', guard(addStudent), 'primary')), listEl),
      detailEl));
    guard(async () => { await loadList(); await loadDetail(); })();
  }

  // ------------------------------------------------------------------ 가족
  function viewFamilies(root) {
    const dir = state.user.is_director;
    let fid = null;
    const listEl = h('ul', { class: 'list' });
    const detailEl = h('div', {});

    async function loadList() {
      const { families } = await api('GET', '/api/families');
      listEl.replaceChildren(...(families.length
        ? families.map((f) => h('li', { class: f.id === fid ? 'active' : '' },
          h('button', { type: 'button', onclick: guard(() => select(f.id)) }, h('span', {}, f.name))))
        : [h('li', { class: 'empty' }, dir ? '가족이 없습니다.' : '담당 학생이 속한 가족이 없습니다.')]));
    }

    async function select(id) { fid = id; await Promise.all([loadList(), loadDetail()]); }

    async function loadDetail() {
      if (fid === null) {
        detailEl.replaceChildren(h('p', { class: 'empty' }, '왼쪽 목록에서 가족을 선택하십시오.'));
        return;
      }
      let d;
      try {
        d = await api('GET', `/api/families/${fid}`);
      } catch (err) {
        if (err.code === 'denied') {
          fid = null;
          detailEl.replaceChildren(h('p', { class: 'empty' }, '열람 권한이 없습니다.'));
          await loadList();
          return;
        }
        throw err;
      }
      const family = d.family;
      const area = h('textarea', { maxlength: 500, 'aria-label': '가족 메모', value: family.memo });
      const counter = h('span', {}, `${[...family.memo].length}/500자`);
      area.addEventListener('input', () => { counter.textContent = `${[...area.value].length}/500자`; });
      const meta = family.memo_updated_at ? `최종 수정: ${family.memo_updated_by || '-'} / ${family.memo_updated_at}` : '';
      const guardianRows = d.guardians.map((g) => {
        const cells = [g.name, g.relation, g.phone, g.contact_restricted ? h('span', { class: 'badge alert' }, '연락 제한') : ''];
        if (dir) {
          cells.push(h('div', { class: 'row-actions' },
            btn('수정', guard(() => editGuardian(g)), 'small'), btn('삭제', guard(() => deleteGuardian(g)), 'small danger')));
        }
        return cells;
      });
      detailEl.replaceChildren(
        card(`${family.name} - 구성원 (학생)`, table(['이름', '학년'], d.students.map((s) => [s.name, s.grade]), '구성원이 없습니다.'),
          dir && actions(btn('이름 변경', guard(() => renameFamily(family))), btn('가족 삭제', guard(deleteFamily), 'danger'))),
        card('보호자 (가족 공통 연락처)',
          table(['이름', '관계', '연락처', '연락 제한'].concat(dir ? [''] : []), guardianRows, '등록된 보호자가 없습니다.'),
          dir && actions(btn('보호자 추가', guard(addGuardian)))),
        card('가족 메모 (원장·강사 열람, 500자 이내)', h('p', { class: 'warn' }, MEMO_WARNING),
          h('div', { class: 'memo' }, area,
            h('div', { class: 'foot' }, h('span', {}, meta), h('span', { class: 'spacer' }), counter,
              btn('메모 저장', guard(() => saveMemo(area.value)), 'primary')))));
    }

    async function saveMemo(text) {
      await api('PUT', `/api/families/${fid}/memo`, { memo: text });
      toast('메모를 저장했습니다.');
      await loadDetail();
    }

    async function addFamily() {
      const id = await formModal({
        title: '가족 추가', fields: [{ key: 'name', label: '가족 이름', maxlength: 100, hint: '예: 김민수 가족' }],
        onSubmit: async (v) => (await api('POST', '/api/families', v)).id,
      });
      if (id) await select(id);
    }

    async function renameFamily(family) {
      const ok = await formModal({
        title: '가족 이름 변경', fields: [{ key: 'name', label: '가족 이름', maxlength: 100 }], initial: { name: family.name },
        onSubmit: (v) => api('PUT', `/api/families/${family.id}`, v),
      });
      if (ok) await select(family.id);
    }

    async function deleteFamily() {
      if (!(await confirmModal('선택한 가족을 삭제하시겠습니까?\n(보호자 정보도 함께 삭제됩니다)', '삭제'))) return;
      await api('DELETE', `/api/families/${fid}`);
      fid = null;
      await Promise.all([loadList(), loadDetail()]);
    }

    const guardianFields = [
      { key: 'name', label: '이름', maxlength: 100 },
      { key: 'relation', label: '관계', maxlength: 30, hint: '예: 어머니, 아버지' },
      { key: 'phone', label: '연락처', maxlength: 30 },
      { key: 'contact_restricted', label: '연락 제한', kind: 'checkbox', text: '알림 발송 대상에서 제외 (알림 기능에서 사용)' },
    ];

    async function addGuardian() {
      const ok = await formModal({
        title: '보호자 추가', fields: guardianFields,
        onSubmit: (v) => api('POST', `/api/families/${fid}/guardians`, v),
      });
      if (ok) await loadDetail();
    }

    async function editGuardian(g) {
      const ok = await formModal({
        title: '보호자 수정', fields: guardianFields,
        initial: { name: g.name, relation: g.relation, phone: g.phone, contact_restricted: !!g.contact_restricted },
        onSubmit: (v) => api('PUT', `/api/guardians/${g.id}`, v),
      });
      if (ok) await loadDetail();
    }

    async function deleteGuardian(g) {
      if (!(await confirmModal(`보호자 '${g.name}' 정보를 삭제하시겠습니까?`, '삭제'))) return;
      await api('DELETE', `/api/guardians/${g.id}`);
      await loadDetail();
    }

    root.append(h('div', { class: 'split' },
      h('aside', { class: 'sidebar' },
        dir && h('div', { class: 'tools' }, btn('가족 추가', guard(addFamily), 'primary')),
        !dir && h('p', { class: 'muted' }, '담당 학생이 속한 가족만 표시됩니다.'), listEl),
      detailEl));
    guard(async () => { await loadList(); await loadDetail(); })();
  }

  // ------------------------------------------------------------------ 수업·특강 (원장)
  function viewClasses(root) {
    const holder = h('div', {});
    const classFields = [
      { key: 'name', label: '수업 이름', maxlength: 100 },
      { key: 'type', label: '유형', kind: 'select', options: [{ value: '정규', label: '정규' }, { value: '특강', label: '특강' }] },
      { key: 'start_date', label: '시작일', kind: 'date', hint: '특강은 시작일·종료일 필수, 정규는 비워도 됩니다.' },
      { key: 'end_date', label: '종료일', kind: 'date' },
      { key: 'fee', label: '금액(원)', inputmode: 'numeric', maxlength: 12, hint: '정규: 월 수강료 / 특강: 전체 기간 총액(1회 청구)' },
    ];

    async function load() {
      const { classes } = await api('GET', '/api/classes');
      const rows = classes.map((c) => [c.name, c.type, c.start_date ? `${c.start_date} ~ ${c.end_date}` : '-', fmtMoney(c.fee),
        c.teachers || '(미지정)',
        h('div', { class: 'row-actions' }, btn('수정', guard(() => edit(c)), 'small'), btn('강사 지정', guard(() => assign(c)), 'small'),
          btn('삭제', guard(() => remove(c)), 'small danger'))]);
      holder.replaceChildren(card('수업·특강', table(['수업', '유형', '기간', '금액 (정규: 월 / 특강: 총액)', '담당 강사', ''], rows, '등록된 수업이 없습니다.'),
        actions(btn('수업 추가', guard(add), 'primary'))));
    }

    async function add() {
      const ok = await formModal({
        title: '수업 추가', fields: classFields, initial: { type: '정규', fee: '0' },
        onSubmit: (v) => api('POST', '/api/classes', v),
      });
      if (ok) await load();
    }

    async function edit(c) {
      const ok = await formModal({
        title: '수업 수정', fields: classFields,
        initial: { name: c.name, type: c.type, start_date: c.start_date || '', end_date: c.end_date || '', fee: String(c.fee) },
        onSubmit: (v) => api('PUT', `/api/classes/${c.id}`, v),
      });
      if (ok) await load();
    }

    async function remove(c) {
      if (!(await confirmModal(`'${c.name}' 수업을 삭제하시겠습니까?`, '삭제'))) return;
      await api('DELETE', `/api/classes/${c.id}`);
      await load();
    }

    async function assign(c) {
      const { candidates, selected } = await api('GET', `/api/classes/${c.id}/teachers`);
      if (!candidates.length) { toast("먼저 '사용자' 탭에서 강사 계정을 추가하십시오.", true); return; }
      const initial = {};
      candidates.forEach((t) => { initial[`t${t.id}`] = selected.includes(t.id); });
      const ok = await formModal({
        title: `강사 지정 - ${c.name}`,
        intro: '담당 강사로 지정하면, 이 수업을 수강하는 학생의 개인정보를 열람할 수 있습니다.',
        fields: candidates.map((t) => ({ key: `t${t.id}`, label: t.name, kind: 'checkbox', text: t.name })),
        initial,
        onSubmit: (v) => api('PUT', `/api/classes/${c.id}/teachers`,
          { user_ids: candidates.filter((t) => v[`t${t.id}`]).map((t) => t.id) }),
      });
      if (ok) await load();
    }

    root.append(holder);
    guard(load)();
  }

  // ------------------------------------------------------------------ 사용자 (원장)
  function viewUsers(root) {
    const holder = h('div', {});
    const pinFields = [
      { key: 'pin', label: 'PIN', kind: 'password', inputmode: 'numeric', maxlength: 6, hint: '숫자 4~6자리' },
      { key: 'pin2', label: 'PIN 확인', kind: 'password', inputmode: 'numeric', maxlength: 6 },
    ];

    async function load() {
      const { users } = await api('GET', '/api/users');
      const rows = users.map((u) => [u.name, u.role, h('span', { class: u.active ? 'badge' : 'badge alert' }, u.active ? '사용' : '중지'),
        h('div', { class: 'row-actions' }, btn('PIN 재설정', guard(() => resetPin(u)), 'small'),
          btn(u.active ? '사용 중지' : '사용 재개', guard(() => toggle(u)), 'small'))]);
      holder.replaceChildren(card('사용자', table(['이름', '역할', '상태', ''], rows), actions(btn('사용자 추가', guard(add), 'primary'))));
    }

    async function add() {
      const ok = await formModal({
        title: '사용자 추가',
        fields: [{ key: 'name', label: '이름', maxlength: 30 },
          { key: 'role', label: '역할', kind: 'select', options: [{ value: '강사', label: '강사' }, { value: '원장', label: '원장' }] }].concat(pinFields),
        initial: { role: '강사' },
        onSubmit: (v) => api('POST', '/api/users', v),
      });
      if (ok) await load();
    }

    async function resetPin(u) {
      const ok = await formModal({
        title: `PIN 재설정 - ${u.name}`, fields: pinFields,
        onSubmit: (v) => api('PUT', `/api/users/${u.id}/pin`, v),
      });
      if (ok) toast('PIN을 변경했습니다.');
    }

    async function toggle(u) {
      await api('PUT', `/api/users/${u.id}/active`, { active: !u.active });
      await load();
    }

    root.append(holder);
    guard(load)();
  }

  // ------------------------------------------------------------------ 설정 (원장)
  function viewSettings(root) {
    const specs = [
      { key: 'grace_leave_months', label: '휴원 후 개인정보 열람 유예 (개월)', hint: '0~36, 기본 3' },
      { key: 'grace_end_months', label: '수강 종료 후 개인정보 열람 유예 (개월)', hint: '0~36, 기본 1' },
      { key: 'auto_lock_minutes', label: '무입력 자동 잠금 (분)', hint: '1~120, 기본 10' },
    ].map((s) => Object.assign({ inputmode: 'numeric', maxlength: 3 }, s));
    const holder = h('div', {});
    let inputs = {};

    async function load() {
      const values = await api('GET', '/api/settings');
      inputs = {};
      holder.replaceChildren(card('설정', specs.map((s) => fieldEl(s, values, inputs)),
        h('p', { class: 'hint' }, '변경한 유예 기간은 진행 중인 건에도 즉시 적용됩니다.'),
        actions(btn('저장', guard(save), 'primary'))));
    }

    async function save() {
      const res = await api('PUT', '/api/settings', readValues(inputs));
      state.lockMinutes = res.auto_lock_minutes;
      toast('저장했습니다.');
      await load();
    }

    root.append(holder);
    guard(load)();
  }

  // ------------------------------------------------------------------ 시작
  (async () => {
    try {
      const s = await api('GET', '/api/state');
      state.lockMinutes = s.lock_minutes;
      if (s.user) { state.user = s.user; renderApp(); } else { await showLogin(); }
    } catch (e) {
      $app.replaceChildren(h('p', { class: 'fatal' }, e.message));
    }
  })();
})();
