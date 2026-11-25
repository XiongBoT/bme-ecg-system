'use strict';
// Shared navigation state; account and record access stay on the server.
var MobileUI = (() => {
  const narrow = window.matchMedia('(max-width: 720px)');
  const stacked = window.matchMedia('(min-width: 721px) and (max-width: 1050px)');
  const shell = $('workspace-shell');
  let current = 'records';
  const scrollPositions = {records: 0, results: 0, devices: 0, account: 0};
  const buttons = ['records', 'devices', 'account'];
  const desktopButtons = {records:'desktop-nav-records', devices:'nav-device', account:'desktop-nav-account'};
  const needsDetail = () => current === 'results' || (!narrow.matches && !stacked.matches && current === 'records');
  const layout = () => narrow.matches ? 'phone' : stacked.matches ? 'tablet' : 'desktop';
  let previousLayout = layout();

  function paint() {
    shell.dataset.mobileView = current;
    for (const name of buttons) {
      for (const id of ['nav-' + name, desktopButtons[name]]) {
        const button = $(id);
        if (name === current || (name === 'records' && current === 'results')) button.setAttribute('aria-current', 'page');
        else button.removeAttribute('aria-current');
      }
    }
  }
  function show(name, {load = true, focus = true} = {}) {
    if (!Object.hasOwn(scrollPositions,name) || (name === 'results' && !state.selected)) return false;
    if (name !== 'results' && document.body?.classList.contains('wave-focus')) $('wave-focus').click();
    if (current !== name) {
      scrollPositions[current] = window.scrollY;
      current = name;
      paint();
      window.scrollTo({top: scrollPositions[name], behavior: 'instant'});
      if (focus) $(name === 'account' ? 'account-heading' : name + '-heading').focus({preventScroll: true});
    }
    if (needsDetail() && load && state.ready) {
      if (!state.wave) detailFeedback('正在读取测量结果…');
      loadWave(); loadAnalysis();
    }
    if (name === 'devices' && load && state.ready) refresh();
    requestAnimationFrame(draw);
    return true;
  }
  function selectionChanged() {
    scrollPositions.results = 0;
    if (!state.selected && current === 'results') show('records', {load: false, focus: false});
    paint();
  }
  function filtersChanged() {
    const active = Object.entries(state.filters).filter(([key, value]) => value && !(key === 'trashed' && value === 'false'));
    text('filter-summary', active.length ? '已设 ' + active.length + ' 项条件' : '全部记录');
    if (narrow.matches) $('filter-panel').open = false;
  }
  function reset() {
    current = 'records';
    for (const key of Object.keys(scrollPositions)) scrollPositions[key] = 0;
    paint(); filtersChanged();
  }
  for (const name of buttons) {
    $('nav-' + name).onclick = () => show(name);
    $(desktopButtons[name]).onclick = () => show(name);
  }
  $('back-records').onclick = () => show('records');
  // A chapter link must focus the destination for keyboard/screen-reader users.
  for (const link of document.querySelectorAll('.result-shortcuts a')) {
    link.addEventListener('click', event => {
      const target = document.getElementById(link.hash.slice(1));
      if (!target || target.hidden) return;
      event.preventDefault();
      target.setAttribute('tabindex', '-1');
      target.focus({preventScroll: true});
      target.scrollIntoView({behavior: 'auto', block: 'start'});
    });
  }
  $('account-install').onclick = () => $('pwa-install').click();
  const installed = window.matchMedia('(display-mode: standalone)');
  const syncInstall = () => {$('account-install').hidden = installed.matches || window.navigator.standalone === true;};
  installed.addEventListener('change', syncInstall);
  window.addEventListener('appinstalled', () => {$('account-install').hidden = true;});
  const resized = () => {
    // Both media queries may fire for one resize; only refresh for the final layout once.
    if (previousLayout === layout()) return;
    previousLayout = layout();
    $('filter-panel').open = !narrow.matches;
    paint();
    if (state.ready && needsDetail()) {loadWave(); loadAnalysis();}
    requestAnimationFrame(draw);
  };
  narrow.addEventListener('change', resized);
  stacked.addEventListener('change', resized);
  $('filter-panel').open = !narrow.matches;
  syncInstall(); paint();
  return {
    reset, selectionChanged, filtersChanged, show,
    needsDetail,
    openResult: () => (narrow.matches || stacked.matches) && show('results'),
  };
})();
