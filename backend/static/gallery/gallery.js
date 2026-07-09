let images = [];
let feedImages = [];
let limits = { originals:{used:0,limit:0}, feed:{used:0,limit:0}, favorites:{used:0,limit:0}, likes:{used:0}, plan:'mini' };
const galleryGrid = document.getElementById('galleryGrid');
const feedGrid = document.getElementById('feedGrid');
const feedSection = document.getElementById('feedSection');
const searchInput = document.getElementById('searchInput');
const filterBtn = document.getElementById('filterBtn');
const filterPopover = document.getElementById('filterPopover');
const viewBtn = document.getElementById('viewBtn');
const toast = document.getElementById('toast');
let currentFilter = 'all';
let listMode = false;
let currentIndex = 0;
let currentCollection = images;
let publishTargetId = null;
let viewerZoom = 1;
let viewerPan = { x: 0, y: 0 };
let viewerDrag = null;
let nextCursor = null;
let hasMoreGallery = false;
let galleryLoading = false;
let galleryLoadError = '';
let searchTimer = null;
let deleteTargetId = null;
let masonryFrame = 0;
const detailPromises = new Map();
const API_BASE = location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

const heartOutline = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 20.3S4.5 16 3.1 10.4C2.2 6.7 4.5 4 7.7 4c1.8 0 3.3 1 4.3 2.4C13 5 14.5 4 16.3 4c3.2 0 5.5 2.7 4.6 6.4C19.5 16 12 20.3 12 20.3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>`;
const heartFilled = `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 21.2 10.7 20C5.4 15.3 2 12.2 2 8.4 2 5.3 4.4 3 7.4 3c1.7 0 3.4.8 4.6 2.1C13.2 3.8 14.9 3 16.6 3 19.6 3 22 5.3 22 8.4c0 3.8-3.4 6.9-8.7 11.6L12 21.2Z"/></svg>`;
const feedIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9L12 3Z" fill="currentColor"/><path d="M5 15l.8 2.2L8 18l-2.2.8L5 21l-.8-2.2L2 18l2.2-.8L5 15Zm14 1 .7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7L19 16Z" fill="currentColor"/></svg>`;
const trashIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 7h14M10 11v6m4-6v6M8 7l.7 12.2c.1 1 1 1.8 2 1.8h2.6c1.1 0 1.9-.8 2-1.8L16 7M9.5 7l.6-2h3.8l.6 2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const openPostIcon = `<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="5" y="5" width="10" height="14" rx="2" stroke="currentColor" stroke-width="1.9"/><path d="M13 5h6v6M19 5l-8 8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function apiUrl(path){ return `${API_BASE}${path}`; }
let refreshSessionPromise = null;
const INSTALL_KEY = 'onenode_installation_id';
const ANON_KEY = 'onenode_anonymous_id';
function localId(key){
  let value = localStorage.getItem(key);
  if(!value){
    value = (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
    localStorage.setItem(key, value);
  }
  return value;
}
function refreshSession(){
  if(!refreshSessionPromise){
    refreshSessionPromise = fetch(apiUrl('/api/auth/session/refresh-v2'), {
      method:'POST',
      credentials:'include',
      headers:{ 'Content-Type':'application/json' },
      body:'{}'
    }).then(res => res.ok).catch(() => false).finally(() => { refreshSessionPromise = null; });
  }
  return refreshSessionPromise;
}
async function tryMiniAppAuth(){
  const tgData = window.Telegram?.WebApp?.initData;
  const maxData = window.MAX?.WebApp?.webAppData || window.MAX?.WebApp?.initData || window.maxWebApp?.webAppData;
  try{
    window.Telegram?.WebApp?.ready?.();
    window.Telegram?.WebApp?.expand?.();
  }catch{}
  try{
    if(tgData){
      const res = await fetch(apiUrl('/api/auth/telegram-v2'), {
        method:'POST',
        credentials:'include',
        headers:{ 'Content-Type':'application/json' },
        body:JSON.stringify({ init_data:tgData, installation_id:localId(INSTALL_KEY), anonymous_id:localId(ANON_KEY), platform:'telegram_mini_app' })
      });
      return res.ok;
    }
    if(maxData){
      const res = await fetch(apiUrl('/api/auth/max-v2'), {
        method:'POST',
        credentials:'include',
        headers:{ 'Content-Type':'application/json' },
        body:JSON.stringify({ web_app_data:maxData, installation_id:localId(INSTALL_KEY), anonymous_id:localId(ANON_KEY), platform:'max_mini_app' })
      });
      return res.ok;
    }
  }catch{}
  return false;
}
async function recoverAuth(){
  if(await refreshSession()) return true;
  return tryMiniAppAuth();
}
async function api(path, options = {}){
  const headers = { ...(options.headers || {}) };
  if(options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  let res = await fetch(apiUrl(path), { credentials:'include', ...options, headers });
  if(res.status === 401){
    const recovered = await recoverAuth();
    if(recovered) res = await fetch(apiUrl(path), { credentials:'include', ...options, headers });
  }
  if(!res.ok){ throw new Error(await res.text() || `HTTP ${res.status}`); }
  return res.json();
}
function showToast(text){ toast.textContent = text; toast.classList.add('show'); clearTimeout(showToast.t); showToast.t = setTimeout(()=>toast.classList.remove('show'), 2400); }
function escapeHtml(s){ return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function allItems(){ return [...images, ...feedImages]; }
function itemById(id){ return images.find(i => String(i.id) === String(id)) || feedImages.find(i => String(i.id) === String(id)); }
function originalById(id){ return images.find(i => String(i.id) === String(id)); }
function favoriteLimit(){ return Number(limits?.favorites?.limit || 0); }
function itemPrompt(item){
  return String(item?.prompt || item?.promptOriginal || item?.promptTranslated || '').trim();
}
function normalizeItem(item){
  const prompt = itemPrompt(item);
  return { ...item, prompt, favorite: Boolean(item.favorite ?? item.isFavorite), modeText: item.modeLabel || modeLabel(item.mode), dateText: formatDate(item.createdAt || item.date), src: apiUrl(item.src || item.thumbnailUrl), viewerSrc: apiUrl(item.viewerSrc || item.downloadUrl || item.src || item.thumbnailUrl), sources: Array.isArray(item.sources) ? item.sources : item.sources };
}
function modeLabel(mode){
  return ({
    text_to_image:'По тексту',
    image_to_image:'По фото',
    edit:'Сборка',
    paint:'Редактор',
    inpaint:'Инпейнт',
    outpaint:'Аутпейнт',
    faceswap:'Лицо',
    try_on:'Примерка',
    texture_transfer:'Перенос текстуры',
    remove_background:'Удаление фона'
  })[String(mode || '').trim()] || 'По тексту';
}
function formatDate(value){
  if(!value) return '';
  const date = new Date(value);
  if(Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('ru-RU', { day:'2-digit', month:'2-digit', year:'2-digit', hour:'2-digit', minute:'2-digit' });
}
function filteredItems(base){
  const q = searchInput.value.trim().toLowerCase();
  return base.filter(raw => {
    const item = normalizeItem(raw);
    if(q){
      const loras = Array.isArray(item.loras) ? item.loras.join(' ') : '';
      const hay = `${item.id} ${item.prompt} ${item.modeText} ${item.model} ${item.preset} ${loras}`.toLowerCase();
      if(!hay.includes(q)) return false;
    }
    if(currentFilter === 'favorite' && !item.favorite) return false;
    if(currentFilter === 'published' && !item.published) return false;
    if(currentFilter === 'unpublished' && item.published) return false;
    if(['16:9','4:5','1:1'].includes(currentFilter) && item.aspectRatio !== currentFilter && item.aspect !== currentFilter) return false;
    if(currentFilter === 'face' && item.modeText !== 'Лицо') return false;
    return true;
  });
}
function cardTemplate(raw, context){
  const item = normalizeItem(raw);
  const promptText = item.prompt || 'Промпт не сохранен';
  const pubPill = item.published && context === 'gallery' ? `<span class="pill feed">В ленте</span>` : '';
  const heartTitle = item.favorite ? 'Убрать сердечко' : 'Поставить сердечко: оставить изображение и защитить от автоудаления';
  const feedTitle = item.published ? 'Открыть публикацию в общей ленте' : 'Опубликовать в ленту';
  const imgAttrs = item.width && item.height ? ` width="${Number(item.width)}" height="${Number(item.height)}"` : '';
  return `<article class="card" data-id="${escapeHtml(item.id)}" data-context="${context}" title="${escapeHtml(promptText)}">
    <img src="${escapeHtml(item.src)}" alt="${escapeHtml(promptText)}" loading="lazy" decoding="async"${imgAttrs}>
    <div class="cardTop"><span class="pill" title="Режим генерации">${escapeHtml(item.modeText)}</span>${pubPill}</div>
    <div class="promptPeek ${item.prompt ? '' : 'empty'}">${escapeHtml(promptText)}</div>
    <div class="cardBottom"><time class="cardDate">${escapeHtml(item.dateText)}</time><div class="cardActions">
      <button class="action heart ${item.favorite?'active':''}" data-action="heart" title="${heartTitle}" aria-label="${heartTitle}">${item.favorite ? heartFilled : heartOutline}</button>
      <button class="action feedAct ${item.published?'feedOn':''}" data-action="feed" title="${feedTitle}" aria-label="${feedTitle}">${feedIcon}</button>
      <button class="action danger" data-action="delete" title="Удалить изображение" aria-label="Удалить изображение">${trashIcon}</button>
    </div></div>
    <div class="listContent"><div class="listPrompt">${escapeHtml(promptText)}</div><div class="listMeta">${escapeHtml(item.dateText)} · ${escapeHtml(item.modeText)}${item.published?' · В ленте':''}</div></div>
  </article>`;
}
function layoutMasonry(){
  masonryFrame = 0;
  document.querySelectorAll('.masonry:not(.list)').forEach(grid => {
    const styles = getComputedStyle(grid);
    const row = parseFloat(styles.getPropertyValue('--masonry-row')) || 8;
    const gap = parseFloat(styles.rowGap) || parseFloat(styles.gap) || 0;
    grid.querySelectorAll('.card').forEach(card => {
      card.style.removeProperty('--masonry-span');
      const height = card.getBoundingClientRect().height;
      const span = Math.max(1, Math.ceil((height + gap) / (row + gap)));
      card.style.setProperty('--masonry-span', String(span));
    });
  });
}
function scheduleMasonry(){
  if(masonryFrame) return;
  masonryFrame = requestAnimationFrame(layoutMasonry);
}
function bindMasonryImages(){
  if(listMode) return;
  document.querySelectorAll('.masonry:not(.list) .card img').forEach(img => {
    if(img.complete) return;
    img.addEventListener('load', scheduleMasonry, { once:true });
    img.addEventListener('error', scheduleMasonry, { once:true });
  });
  scheduleMasonry();
}
function render(){
  const galleryItems = filteredItems(images);
  const feedItems = filteredItems(feedImages);
  galleryGrid.classList.toggle('list', listMode);
  feedGrid.classList.toggle('list', listMode);
  feedSection.hidden = Boolean(galleryLoadError);
  if(galleryLoadError){
    galleryGrid.innerHTML = `<div class="empty errorState"><strong>Галерея не загрузилась</strong><p>${escapeHtml(galleryLoadError)}</p><p style="margin-top:14px"><button class="btn acid" data-action="retry-gallery">Повторить</button></p></div>`;
    feedGrid.innerHTML = '';
  }else if(galleryLoading && images.length === 0){
    galleryGrid.innerHTML = `<div class="skeletonGrid">${Array.from({length:8}).map(()=>'<div class="skeletonCard"></div>').join('')}</div>`;
    feedGrid.innerHTML = `<div class="skeletonGrid">${Array.from({length:4}).map(()=>'<div class="skeletonCard"></div>').join('')}</div>`;
  }else{
    const emptyText = searchInput.value.trim() || currentFilter !== 'all' ? 'По выбранному поиску и фильтру ничего не найдено.' : 'Галерея пока пуста.';
    const resetAction = searchInput.value.trim() || currentFilter !== 'all'
      ? `<p style="margin-top:14px"><button class="btn" data-action="reset-gallery-filters">Сбросить поиск и фильтр</button></p>`
      : '';
    galleryGrid.innerHTML = galleryItems.length ? galleryItems.map(i=>cardTemplate(i,'gallery')).join('') : `<div class="empty"><strong>Ничего не найдено</strong><p>${emptyText}</p>${resetAction}</div>`;
    feedGrid.innerHTML = feedItems.length ? feedItems.map(i=>cardTemplate(i,'feed')).join('') : `<div class="empty">Публикаций по выбранному фильтру нет.</div>`;
  }
  const galleryCountEl = document.getElementById('galleryCount');
  galleryCountEl.textContent = `${limits.originals.used} / ${limits.originals.limit}`;
  galleryCountEl.parentElement.classList.toggle('overLimit', Number(limits.originals.used || 0) > Number(limits.originals.limit || 0));
  document.getElementById('feedCount').textContent = `${limits.feed.used} / ${limits.feed.limit}`;
  const favCountEl = document.getElementById('favCount');
  favCountEl.textContent = `${limits.favorites.used} / ${favoriteLimit()}`;
  favCountEl.parentElement.classList.toggle('overLimit', Number(limits.favorites.used || 0) > Number(favoriteLimit() || 0));
  document.getElementById('likesCount').textContent = String(Number(limits.likes?.used || 0));
  const feedSectionCount = document.getElementById('feedSectionCount');
  if(feedSectionCount) feedSectionCount.textContent = `${feedItems.length} публикаций`;
  const loadMoreBtn = document.getElementById('loadMoreBtn');
  loadMoreBtn.hidden = !hasMoreGallery || Boolean(galleryLoadError);
  loadMoreBtn.textContent = galleryLoading ? 'Загружаем...' : 'Показать еще';
  loadMoreBtn.disabled = galleryLoading;
  bindMasonryImages();
}
async function loadGallery({ append = false } = {}){
  if(galleryLoading) return;
  galleryLoading = true;
  if(!append) galleryLoadError = '';
  render();
  try{
    const params = new URLSearchParams({ limit: '60' });
    if(append && nextCursor) params.set('cursor', nextCursor);
    const q = searchInput.value.trim();
    if(q) params.set('q', q);
    if(currentFilter !== 'all') params.set('filter', currentFilter);
    const data = await api(`/api/gallery/page?${params.toString()}`);
    limits = data.limits || limits;
    const nextImages = (data.items || []).map(normalizeItem);
    const nextFeedImages = (data.feedItems || []).map(normalizeItem);
    images = append ? [...images, ...nextImages] : nextImages;
    feedImages = append ? [...feedImages, ...nextFeedImages] : nextFeedImages;
    nextCursor = data.nextCursor || null;
    hasMoreGallery = Boolean(data.hasMore);
    currentCollection = images;
    render();
  }catch(err){
    if(!append) galleryLoadError = String(err?.message || '').includes('Missing session token')
      ? 'Войдите в аккаунт, чтобы открыть личную галерею.'
      : 'Проверьте авторизацию или попробуйте обновить страницу.';
    if(append) showToast('Галерея не загрузилась.');
    console.error(err);
    galleryLoading = false;
    render();
    return;
  }finally{
    galleryLoading = false;
    render();
  }
}
async function hydrateProfileLabel(){
  const label = document.querySelector('.user-label');
  const account = document.querySelector('.account-button');
  if(!label) return;
  try{
    const me = await api('/api/me-v2');
    const name = me?.profile?.display_name || me?.profile?.username || 'Профиль';
    label.textContent = String(name).slice(0, 24);
    account?.setAttribute('title', 'Профиль и настройки');
    account?.setAttribute('aria-label', 'Профиль и настройки');
  }catch{
    label.textContent = 'Войти';
    account?.setAttribute('title', 'Войти в аккаунт');
    account?.setAttribute('aria-label', 'Войти в аккаунт');
  }
}
async function toggleFavorite(id){
  const item = originalById(id); if(!item) return;
  if(!item.favorite && favoriteLimit() && limits.favorites.used >= favoriteLimit()){ showToast(`Лимит сердечек: максимум ${favoriteLimit()}.`); return; }
  const next = !item.favorite;
  try{
    await api(`/api/gallery/${encodeURIComponent(id)}/favorite`, { method:'POST', body:JSON.stringify({ isFavorite: next }) });
    images = images.map(raw => String(raw.id) === String(id) ? { ...raw, favorite: next, isFavorite: next } : raw);
    feedImages = feedImages.map(raw => String(raw.id) === String(id) ? { ...raw, favorite: next, isFavorite: next } : raw);
    limits = { ...limits, favorites: { ...limits.favorites, used: Math.max(0, Number(limits.favorites.used || 0) + (next ? 1 : -1)) } };
    showToast(next ? 'Сердечко поставлено. Изображение защищено.' : 'Сердечко убрано.');
    render();
    if(document.getElementById('viewer').classList.contains('open')) updateViewer();
  }catch(err){ showToast('Не удалось изменить сердечко.'); console.error(err); }
}
async function feedAction(id){
  const item = originalById(id); if(!item) return;
  if(item.published){ window.location.href = '/feed'; return; }
  openPublishModal(id);
}
function openPublishModal(id){
  const item = originalById(id); if(!item) return;
  publishTargetId = id;
  document.getElementById('publishTitle').value = '';
  document.getElementById('publishPromptOpen').checked = true;
  openSmall('publishModal');
  setTimeout(()=>document.getElementById('publishTitle').focus(), 0);
}
async function submitPublish(){
  const id = publishTargetId;
  const item = originalById(id); if(!item) return;
  const title = document.getElementById('publishTitle').value.trim();
  if(!title){ showToast('Нужно название публикации.'); return; }
  const promptVisibility = document.getElementById('publishPromptOpen').checked ? 'open' : 'hidden';
  const submitBtn = document.getElementById('publishSubmitBtn');
  submitBtn.disabled = true;
  try{
    await api('/api/feed/publications', { method:'POST', body:JSON.stringify({ imageId:id, title, promptVisibility, allowRecreate:true }) });
    closeSmalls();
    await loadGallery();
    showToast('Изображение опубликовано в ленту.');
    if(document.getElementById('viewer').classList.contains('open')) updateViewer();
  }catch(err){ showToast('Не удалось опубликовать в ленту.'); console.error(err); }
  finally{ submitBtn.disabled = false; }
}
async function deleteImage(id){
  const item = originalById(id); if(!item) return;
  deleteTargetId = id;
  document.getElementById('deleteText').textContent = item.published
    ? 'Изображение будет удалено из галереи, публикация в ленте будет снята, а слот освободится.'
    : 'Изображение будет удалено из галереи, а слот освободится.';
  openSmall('deleteModal');
}
async function confirmDeleteImage(){
  const id = deleteTargetId;
  const item = originalById(id); if(!item) return;
  const deleteBtn = document.getElementById('deleteConfirmBtn');
  deleteBtn.disabled = true;
  try{
    await api(`/api/gallery/${encodeURIComponent(id)}`, { method:'DELETE' });
    const viewerOpen = document.getElementById('viewer').classList.contains('open');
    if(viewerOpen) closeViewer();
    closeSmalls();
    images = images.filter(raw => String(raw.id) !== String(id));
    feedImages = feedImages.filter(raw => String(raw.id) !== String(id));
    limits = {
      ...limits,
      originals: { ...limits.originals, used: Math.max(0, Number(limits.originals.used || 0) - 1), free: Math.max(0, Number(limits.originals.free || 0) + 1), full: false },
      favorites: { ...limits.favorites, used: item.favorite ? Math.max(0, Number(limits.favorites.used || 0) - 1) : Number(limits.favorites.used || 0) },
      feed: { ...limits.feed, used: item.published ? Math.max(0, Number(limits.feed.used || 0) - 1) : Number(limits.feed.used || 0) }
    };
    render();
    showToast('Изображение удалено. Место освобождено.');
  }catch(err){ showToast('Не удалось удалить изображение.'); console.error(err); }
  finally{
    deleteTargetId = null;
    deleteBtn.disabled = false;
  }
}
function openViewerById(id, collection){
  currentCollection = collection && collection.length ? collection.map(normalizeItem) : images;
  currentIndex = currentCollection.findIndex(i=>String(i.id)===String(id));
  if(currentIndex < 0){ currentCollection = images; currentIndex = images.findIndex(i=>String(i.id)===String(id)); }
  document.getElementById('viewer').classList.add('open');
  document.body.style.overflow = 'hidden';
  resetViewerZoom();
  updateViewer();
}
function updateViewer(){
  const baseItem = currentCollection[currentIndex] ? normalizeItem(currentCollection[currentIndex]) : null; if(!baseItem) return;
  const item = normalizeItem(itemById(baseItem.id) || baseItem);
  const promptText = item.prompt || 'Промпт не сохранен';
  document.getElementById('viewerImg').src = item.viewerSrc || item.src;
  document.getElementById('viewerImg').alt = promptText;
  document.getElementById('viewerCounter').textContent = `${currentIndex+1} / ${currentCollection.length}`;
  document.getElementById('viewerMode').textContent = item.modeText;
  document.getElementById('viewerDate').textContent = item.dateText;
  document.getElementById('viewerPub').hidden = !item.published;
  const heartBtn = document.getElementById('heartBtn');
  heartBtn.textContent = item.favorite ? '♥' : '♡';
  heartBtn.classList.toggle('acid', item.favorite);
  const feedBtn = document.getElementById('feedBtn');
  feedBtn.textContent = item.published ? '✦ Пост' : '✦ В ленту';
  const publishTopBtn = document.getElementById('viewerPublishBtn');
  publishTopBtn.innerHTML = item.published ? openPostIcon : feedIcon;
  publishTopBtn.title = item.published ? 'Открыть публикацию в ленте' : 'Опубликовать в ленту';
  publishTopBtn.setAttribute('aria-label', publishTopBtn.title);
  const downloadBtn = document.getElementById('downloadBtn');
  downloadBtn.href = item.viewerSrc || item.src;
  downloadBtn.setAttribute('download', `izo-asa-${item.id}.png`);
  const desktopDownloadBtn = document.getElementById('desktopDownloadBtn');
  desktopDownloadBtn.href = item.viewerSrc || item.src;
  desktopDownloadBtn.setAttribute('download', `izo-asa-${item.id}.png`);
  document.getElementById('viewerPrompt').textContent = promptText;
  renderSources(item); renderPublication(item); renderParams(item); renderThumbs();
  loadViewerDetail(item.id);
}
function renderSources(item){
  const wrap = document.getElementById('sourceContent');
  if(Array.isArray(item.sources)){
    if(item.sources.length === 0){ wrap.innerHTML = `<p>Исходников нет: изображение создано из текста.</p>`; return; }
    wrap.innerHTML = `<div class="sourceTree">${item.sources.map((source,n)=>sourceNodeTemplate(source,n,0)).join('')}</div>`;
    return;
  }
  if(item.sourceIds && item.sourceIds.length){
    wrap.innerHTML = `<div class="sourceGrid">${item.sourceIds.map((sid,n)=>{ const s=normalizeItem(itemById(sid)); return s ? `<div class="sourceItem"><img src="${escapeHtml(s.src)}" alt="Исходник ${n+1}" loading="lazy" decoding="async"><span>Исходник ${n+1}</span><small>из галереи</small></div>` : ''; }).join('')}</div>`;
    return;
  }
  wrap.innerHTML = `<p>Проверяем исходники...</p>`;
}
function sourceNodeTemplate(source, index, depth){
  const thumb = apiUrl(source.thumbUrl || source.thumbnailUrl || '');
  const label = source.roleLabel || `Исходник ${index+1}`;
  const linked = source.sourceImageId ? 'из галереи' : String(source.sourceKind || 'upload');
  const children = Array.isArray(source.children) ? source.children : [];
  return `<div class="sourceNode depth${Math.min(depth,3)}">
    <button class="sourceItem" type="button" data-source-id="${escapeHtml(source.sourceImageId || '')}" title="${escapeHtml(label)}">
      <img src="${escapeHtml(thumb)}" alt="${escapeHtml(label)}" loading="lazy" decoding="async">
      <span>${escapeHtml(label)}</span><small>${escapeHtml(linked)}</small>
    </button>
    ${children.length ? `<div class="sourceChildren">${children.map((child,n)=>sourceNodeTemplate(child,n,depth+1)).join('')}</div>` : ''}
  </div>`;
}
async function loadViewerDetail(id){
  if(!id || detailPromises.has(String(id))) return;
  const currentId = String(id);
  const promise = api(`/api/gallery/${encodeURIComponent(currentId)}`)
    .then(detail => {
      images = images.map(raw => String(raw.id) === currentId ? { ...raw, ...detail, sources: detail.sources || [] } : raw);
      feedImages = feedImages.map(raw => String(raw.id) === currentId ? { ...raw, ...detail, sources: detail.sources || [] } : raw);
      currentCollection = currentCollection.map(raw => String(raw.id) === currentId ? { ...raw, ...detail, sources: detail.sources || [] } : raw);
      if(document.getElementById('viewer').classList.contains('open') && String(currentCollection[currentIndex]?.id) === currentId){
        renderSources(normalizeItem(currentCollection[currentIndex]));
      }
    })
    .catch(err => {
      console.error(err);
      const wrap = document.getElementById('sourceContent');
      if(document.getElementById('viewer').classList.contains('open') && String(currentCollection[currentIndex]?.id) === currentId){
        wrap.innerHTML = `<p>Исходники не удалось загрузить.</p>`;
      }
    })
    .finally(() => detailPromises.delete(currentId));
  detailPromises.set(currentId, promise);
}
async function openSourceImage(sourceId){
  if(!sourceId){ showToast('Это сохраненный снимок: исходник уже не открывается.'); return; }
  const existing = itemById(sourceId);
  if(existing){
    const collection = images.some(item => String(item.id) === String(sourceId)) ? images : [normalizeItem(existing)];
    openViewerById(sourceId, collection);
    return;
  }
  try{
    const detail = await api(`/api/gallery/${encodeURIComponent(sourceId)}`);
    const item = normalizeItem({ ...detail, sources: detail.sources || [] });
    images = images.some(raw => String(raw.id) === String(sourceId)) ? images.map(raw => String(raw.id) === String(sourceId) ? { ...raw, ...item } : raw) : [item, ...images];
    openViewerById(sourceId, [item]);
  }catch(err){
    showToast('Исходник удален. Остался только сохраненный снимок цепочки.');
    console.error(err);
  }
}
function renderPublication(item){
  const wrap = document.getElementById('publicationContent');
  if(!item.published){ wrap.innerHTML = `<p>Это изображение пока не опубликовано. При публикации будет создана отдельная WebP-копия для ленты, оригинал останется в галерее.</p><p style="margin-top:10px"><button class="btn acid" id="publishSelectedBtnInline">Опубликовать в ленту</button></p>`; return; }
  wrap.innerHTML = `<p>Опубликовано: <b>${escapeHtml(formatDate(item.publishedAt || item.createdAt))}</b>. В ленте хранится отдельная WebP-копия.</p><div class="stats"><div class="stat"><strong>${escapeHtml(item.views || 0)}</strong><span>Просмотры</span></div><div class="stat"><strong>${item.likes || 0}</strong><span>Лайки</span></div><div class="stat"><strong>${item.saves || 0}</strong><span>Сохранения</span></div><div class="stat"><strong>${item.remixes || 0}</strong><span>Ремиксы</span></div></div>`;
}
function renderParams(item){
  const lora = Array.isArray(item.loras) && item.loras.length ? item.loras.map(l=>l.name || l.id || l).join(', ') : '—';
  document.getElementById('paramsContent').innerHTML = [
    ['Модель', item.model || item.modelProfile || 'Flux2'], ['Пресет', item.preset || '—'], ['LoRA', lora], ['Seed', item.seed ?? '—'], ['Размер', `${item.width || 0}×${item.height || 0}`], ['Время', item.generationTimeMs ? `${Math.round(item.generationTimeMs/100)/10} c` : '—'], ['ID', item.id], ['Режим', item.modeText]
  ].map(([k,v])=>`<div class="param"><span>${escapeHtml(k)}</span><b>${escapeHtml(v)}</b></div>`).join('');
}
function renderThumbs(){
  const radius = 12;
  const start = Math.max(0, currentIndex - radius);
  const end = Math.min(currentCollection.length, currentIndex + radius + 1);
  const prefix = start > 0 ? `<span class="pill" title="Ранее в подборке">+${start}</span>` : '';
  const suffixCount = currentCollection.length - end;
  const suffix = suffixCount > 0 ? `<span class="pill" title="Дальше в подборке">+${suffixCount}</span>` : '';
  const thumbs = currentCollection.slice(start, end).map((raw,offset)=>{ const idx=start+offset; const item=normalizeItem(raw); return `<button class="thumb ${idx===currentIndex?'active':''}" data-idx="${idx}"><img src="${escapeHtml(item.src)}" alt="" loading="lazy" decoding="async"></button>`; }).join('');
  document.getElementById('thumbRail').innerHTML = `${prefix}${thumbs}${suffix}`;
}
function closeViewer(){ document.getElementById('viewer').classList.remove('open'); document.body.style.overflow = ''; resetViewerZoom(); }
function stepViewer(dir){ currentIndex = (currentIndex + dir + currentCollection.length) % currentCollection.length; resetViewerZoom(); updateViewer(); }
function openSmall(id){ document.getElementById(id).classList.add('open'); }
function closeSmalls(){ document.querySelectorAll('.smallModal').forEach(m=>m.classList.remove('open')); }
function showSpace(){ document.getElementById('spaceText').textContent = `${limits.originals.used} из ${limits.originals.limit} мест в галерее, ${limits.feed.used} публикаций в ленте, ${limits.favorites.used} из ${favoriteLimit()} сердечек, ${Number(limits.likes?.used || 0)} лайков в ленте. Тариф: ${String(limits.plan || '').toUpperCase()}.`; openSmall('spaceModal'); }
function closeMenus(except){
  document.querySelectorAll('.dropMenu.open').forEach(menu => { if(menu !== except) menu.classList.remove('open'); });
}
function currentItem(){
  return currentCollection[currentIndex] ? normalizeItem(currentCollection[currentIndex]) : null;
}
function applyViewerZoom(){
  const img = document.getElementById('viewerImg');
  const stage = document.querySelector('.viewerStage');
  img.style.transform = `translate(${viewerPan.x}px, ${viewerPan.y}px) scale(${viewerZoom})`;
  document.getElementById('viewerZoomText').textContent = `${Math.round(viewerZoom * 100)}%`;
  document.getElementById('desktopViewerZoomText').textContent = `${Math.round(viewerZoom * 100)}%`;
  stage.classList.toggle('zoomed', viewerZoom > 1.01);
}
function resetViewerZoom(){
  viewerZoom = 1;
  viewerPan = { x: 0, y: 0 };
  viewerDrag = null;
  applyViewerZoom();
}
function changeViewerZoom(delta){
  const next = Math.max(0.5, Math.min(4, Number((viewerZoom + delta).toFixed(2))));
  viewerZoom = next;
  if(viewerZoom <= 1.01) viewerPan = { x: 0, y: 0 };
  applyViewerZoom();
}
async function copyText(text, success){
  try{
    await navigator.clipboard.writeText(text);
    showToast(success);
  }catch(err){
    showToast('Не удалось скопировать.');
    console.error(err);
  }
}
async function shareCurrent(kind){
  const item = currentItem(); if(!item) return;
  const url = new URL(item.viewerSrc || item.src, window.location.origin).href;
  const text = item.prompt || 'Изображение ИЗО АСА';
  if(kind === 'copy') return copyText(url, 'Ссылка скопирована.');
  if(navigator.share && (kind === 'telegram' || kind === 'max' || kind === 'vk')){
    try{ await navigator.share({ title:'ИЗО АСА', text, url }); showToast('Открыли системный шаринг.'); return; }catch(err){ if(err?.name === 'AbortError') return; }
  }
  const encodedUrl = encodeURIComponent(url);
  const encodedText = encodeURIComponent(text);
  const links = {
    telegram: `https://t.me/share/url?url=${encodedUrl}&text=${encodedText}`,
    vk: `https://vk.com/share.php?url=${encodedUrl}&title=${encodedText}`,
    max: url
  };
  if(kind === 'max') return copyText(url, 'Ссылка для MAX скопирована.');
  window.open(links[kind] || url, '_blank', 'noopener,noreferrer');
}
async function useCurrentAs(target){
  const item = currentItem(); if(!item) return;
  try{
    const data = await api(`/api/gallery/${encodeURIComponent(item.imageId || item.id)}/use-as`, { method:'POST', body:JSON.stringify({ target }) });
    sessionStorage.setItem('izoUseAsDraft', JSON.stringify({ ...data, source:'gallery', createdAt:new Date().toISOString() }));
    const routes = { editor:'/#editor', image:'/#image-to-image', face:'/#face', draw:'/paint' };
    window.location.href = routes[target] || '/';
  }catch(err){
    showToast('Не удалось подготовить изображение.');
    console.error(err);
  }
}

function resetGalleryFilters(){
  searchInput.value = '';
  currentFilter = 'all';
  filterPopover.querySelectorAll('button').forEach(b=>b.classList.toggle('active', b.dataset.filter === 'all'));
  loadGallery();
}

galleryGrid.addEventListener('click', e=>{ if(e.target.closest('[data-action="retry-gallery"]')) return loadGallery(); if(e.target.closest('[data-action="reset-gallery-filters"]')) return resetGalleryFilters(); const card=e.target.closest('.card'); if(!card) return; const id=card.dataset.id; if(e.target.closest('[data-action="heart"]')) return toggleFavorite(id); if(e.target.closest('[data-action="feed"]')) return feedAction(id); if(e.target.closest('[data-action="delete"]')) return deleteImage(id); openViewerById(id, filteredItems(images)); });
feedGrid.addEventListener('click', e=>{ const card=e.target.closest('.card'); if(!card) return; const id=card.dataset.id; if(e.target.closest('[data-action="heart"]')) return toggleFavorite(id); if(e.target.closest('[data-action="feed"]')) return feedAction(id); if(e.target.closest('[data-action="delete"]')) return deleteImage(id); openViewerById(id, filteredItems(feedImages)); });
searchInput.addEventListener('input', ()=>{
  clearTimeout(searchTimer);
  searchTimer = setTimeout(()=>loadGallery(), 260);
});
filterBtn.addEventListener('click', ()=>filterPopover.classList.toggle('open'));
filterPopover.addEventListener('click', e=>{ const btn=e.target.closest('button[data-filter]'); if(!btn) return; currentFilter=btn.dataset.filter; filterPopover.querySelectorAll('button').forEach(b=>b.classList.toggle('active', b===btn)); filterPopover.classList.remove('open'); loadGallery(); });
viewBtn.addEventListener('click', ()=>{ listMode=!listMode; viewBtn.textContent=listMode?'▦':'☷'; render(); });
window.addEventListener('resize', scheduleMasonry);
document.getElementById('loadMoreBtn').addEventListener('click', ()=>loadGallery({ append:true }));
if('IntersectionObserver' in window){
  const moreObserver = new IntersectionObserver(entries => {
    if(entries.some(entry => entry.isIntersecting) && hasMoreGallery && !galleryLoading && !galleryLoadError){
      loadGallery({ append:true });
    }
  }, { rootMargin:'600px 0px' });
  moreObserver.observe(document.getElementById('loadMoreBtn'));
}
document.getElementById('viewerClose').addEventListener('click', closeViewer);
document.getElementById('prevBtn').addEventListener('click', ()=>stepViewer(-1));
document.getElementById('nextBtn').addEventListener('click', ()=>stepViewer(1));
document.getElementById('thumbRail').addEventListener('click', e=>{ const b=e.target.closest('.thumb'); if(!b) return; currentIndex=Number(b.dataset.idx); resetViewerZoom(); updateViewer(); });
document.getElementById('heartBtn').addEventListener('click', ()=>toggleFavorite(currentCollection[currentIndex]?.id));
document.getElementById('feedBtn').addEventListener('click', ()=>feedAction(currentCollection[currentIndex]?.id));
document.getElementById('viewerPublishBtn').addEventListener('click', ()=>feedAction(currentCollection[currentIndex]?.id));
document.getElementById('deleteBtn').addEventListener('click', ()=>deleteImage(currentCollection[currentIndex]?.id));
document.getElementById('viewerDeleteBtn').addEventListener('click', ()=>deleteImage(currentCollection[currentIndex]?.id));
document.getElementById('publishSelectedBtn').addEventListener('click', ()=>feedAction(currentCollection[currentIndex]?.id || images[0]?.id));
document.getElementById('publicationContent').addEventListener('click', e=>{ if(e.target.closest('#publishSelectedBtnInline')) feedAction(currentCollection[currentIndex]?.id); });
document.getElementById('sourceContent').addEventListener('click', e=>{ const btn=e.target.closest('[data-source-id]'); if(!btn) return; openSourceImage(btn.dataset.sourceId); });
document.getElementById('publishForm').addEventListener('submit', e=>{ e.preventDefault(); submitPublish(); });
document.getElementById('publishCancelBtn').addEventListener('click', closeSmalls);
document.getElementById('deleteCancelBtn').addEventListener('click', closeSmalls);
document.getElementById('deleteConfirmBtn').addEventListener('click', confirmDeleteImage);
document.getElementById('zoomOutBtn').addEventListener('click', ()=>changeViewerZoom(-0.25));
document.getElementById('zoomInBtn').addEventListener('click', ()=>changeViewerZoom(0.25));
document.getElementById('zoomResetBtn').addEventListener('click', resetViewerZoom);
document.getElementById('desktopZoomOutBtn').addEventListener('click', ()=>changeViewerZoom(-0.25));
document.getElementById('desktopZoomInBtn').addEventListener('click', ()=>changeViewerZoom(0.25));
document.getElementById('desktopZoomResetBtn').addEventListener('click', resetViewerZoom);
document.querySelector('.viewerStage').addEventListener('wheel', e=>{ e.preventDefault(); changeViewerZoom(e.deltaY > 0 ? -0.18 : 0.18); }, { passive:false });
document.querySelector('.viewerStage').addEventListener('dblclick', e=>{ if(e.target.closest('button,a')) return; viewerZoom = viewerZoom > 1.01 ? 1 : 2; if(viewerZoom === 1) viewerPan = { x:0, y:0 }; applyViewerZoom(); });
document.querySelector('.viewerStage').addEventListener('pointerdown', e=>{ if(viewerZoom <= 1.01 || e.target.closest('button,a')) return; viewerDrag = { id:e.pointerId, x:e.clientX, y:e.clientY, pan:{...viewerPan} }; e.currentTarget.setPointerCapture(e.pointerId); e.currentTarget.classList.add('dragging'); });
document.querySelector('.viewerStage').addEventListener('pointermove', e=>{ if(!viewerDrag || e.pointerId !== viewerDrag.id) return; viewerPan = { x: viewerDrag.pan.x + e.clientX - viewerDrag.x, y: viewerDrag.pan.y + e.clientY - viewerDrag.y }; applyViewerZoom(); });
document.querySelector('.viewerStage').addEventListener('pointerup', e=>{ if(!viewerDrag || e.pointerId !== viewerDrag.id) return; viewerDrag = null; e.currentTarget.classList.remove('dragging'); });
document.querySelector('.viewerStage').addEventListener('pointercancel', e=>{ viewerDrag = null; e.currentTarget.classList.remove('dragging'); });
document.getElementById('spaceBtn').addEventListener('click', showSpace);
document.getElementById('helpBtn').addEventListener('click', ()=>openSmall('helpModal'));
document.querySelectorAll('[data-close-small]').forEach(b=>b.addEventListener('click', closeSmalls));
document.addEventListener('keydown', e=>{ if(e.key==='Escape'){ closeViewer(); closeSmalls(); } if(document.getElementById('viewer').classList.contains('open') && e.key==='ArrowRight') stepViewer(1); if(document.getElementById('viewer').classList.contains('open') && e.key==='ArrowLeft') stepViewer(-1); });
document.getElementById('createBtn').addEventListener('click', ()=>{ window.location.href = '/#text-to-image'; });
document.querySelector('[data-action="help"]')?.addEventListener('click', ()=>openSmall('helpModal'));
document.getElementById('openFeedBtn').addEventListener('click', ()=>{ window.location.href = '/feed'; });
document.getElementById('editBtn').addEventListener('click', e=>{ const menu=document.getElementById('editMenu'); menu.classList.toggle('open'); closeMenus(menu.classList.contains('open') ? menu : null); e.stopPropagation(); });
document.getElementById('shareBtn').addEventListener('click', e=>{ const menu=document.getElementById('shareMenu'); menu.classList.toggle('open'); closeMenus(menu.classList.contains('open') ? menu : null); e.stopPropagation(); });
document.getElementById('editMenu').addEventListener('click', e=>{ const btn=e.target.closest('[data-edit]'); if(!btn) return; closeMenus(); useCurrentAs(btn.dataset.edit); });
document.getElementById('shareMenu').addEventListener('click', e=>{ const btn=e.target.closest('[data-share]'); if(!btn) return; closeMenus(); shareCurrent(btn.dataset.share); });
document.addEventListener('click', e=>{ if(!e.target.closest('.dropHost')) closeMenus(); });
hydrateProfileLabel();
loadGallery();

