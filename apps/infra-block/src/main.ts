import './style.css';
import '@fontsource/barlow-condensed/700.css';
import '@fontsource/dm-sans/400.css';
import { nodes } from './data';
import { createWorld } from './world';
import { createGame, tick, stomp, grabThrow, start, pause, resume } from './game';
import type { GameState, CharacterId, WorldController, Layer, WorldEvent, CrewControlState } from './contracts';
import { crewInputAllowed } from './crew-input';
import { RESIDENTS } from './residents';
import { Audio as SoundEngine } from './audio';
import { exportScorecard, challengeUrl, ReplayRecorder } from './export';
import { mountCockpit } from './ops';
import { mountHome } from './home';

function escapeHtml(str: unknown): string {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

type Lang = 'en' | 'zh';
const i18n = {
  en: {
    subBrand: 'Infrastructure',
    explore: 'Explore',
    sandbox: 'Sandbox',
    mute: 'Mute',
    unmute: 'Sound',
    help: 'Help',
    heroTitle: 'Infrastructure, alive.',
    heroSub: 'Source map · Browser simulation',
    layers: 'Layers',
    allLayers: 'All Layers',
    searchPh: 'Search nodes (e.g. hermes, fleet)...',
    walkthrough: 'Guided Walkthrough',
    prev: 'Prev',
    next: 'Next',
    nodes: 'System Nodes',
    inspectorEmpty: 'Select any node from the canvas, navigator, or guided tour to inspect source contracts.',
    sources: 'Source Contracts',
    relations: 'Relationships',
    evidence: 'Evidence',
    evidenceNote: 'Audit Verification',
    character: 'Select Operative',
    munch: 'MUNCH (Heavy Brawler)',
    bongo: 'BONGO (Speed Courier)',
    bolt: 'BOLT (High-Voltage)',
    startRound: 'Start 45s Simulation',
    time: 'Time Remaining',
    score: 'Score',
    destroyed: 'Destroyed',
    multiplier: 'Multiplier',
    stomp: 'Stomp (R)',
    grab: 'Grab / Throw (E)',
    attack: 'Attack (Space)',
    pause: 'Pause',
    paused: 'Simulation Paused',
    resume: 'Resume',
    retry: 'Retry Run',
    home: 'Return to Source Map',
    victory: 'Run Completed',
    defeat: 'Simulation Terminated',
    bestCombo: 'Best Combo Chain',
    sharePng: 'Export Scorecard PNG',
    copyLink: 'Copy Challenge Link',
    copied: 'Link copied to clipboard!',
    helpTitle: 'Snow Gloves OS · Operations Manual',
    helpBody: 'Explore: Walk as a crew member with WASD / arrows. Press 1–7 to switch roles and E to meet a nearby station. Choose Overview to return to the town view. Touch directions provide the same movement. Manual walking is local exploration; observed work status comes from the connected source projection.\n\nSandbox: Move toy monsters through the miniature city.\nControls: WASD / arrows to move, Space (hold) to attack, E to Grab/Throw items, R to Stomp, ESC to Pause.',
    close: 'Close',
    webglFail: 'WebGL 3D canvas could not initialize. Rendering 2D fallback data map.'
  },
  zh: {
    subBrand: '基础设施总线',
    explore: '架构拓扑',
    sandbox: '沙盒模拟',
    mute: '静音',
    unmute: '音频',
    help: '手册',
    heroTitle: '活性基础设施总线',
    heroSub: '源码图谱 · 浏览器原生仿真',
    layers: '架构分层',
    allLayers: '全部分层',
    searchPh: '搜索系统节点 (例如 hermes, fleet)...',
    walkthrough: '引导式巡检',
    prev: '上一个',
    next: '下一个',
    nodes: '系统拓扑节点',
    inspectorEmpty: '从画布、导航底栏或巡检流程中选择任意节点以查看源码规约。',
    sources: '源码定义',
    relations: '关联合约',
    evidence: '凭证级别',
    evidenceNote: '审计核验说明',
    character: '选择作业单元',
    munch: 'MUNCH (重装突破型)',
    bongo: 'BONGO (高速信使型)',
    bolt: 'BOLT (高压伏特型)',
    startRound: '启动 45秒 沙盒运转',
    time: '剩余时间',
    score: '运行时得分',
    destroyed: '清除载荷',
    multiplier: '倍率增益',
    stomp: '重踏 (R)',
    grab: '抓取 / 投掷 (E)',
    attack: '脉冲打击 (Space)',
    pause: '暂停',
    paused: '模拟已暂停',
    resume: '继续',
    retry: '重新开始',
    home: '返回架构图谱',
    victory: '模拟测试完成',
    defeat: '模拟终止',
    bestCombo: '最佳连击链',
    sharePng: '导出计分卡 PNG',
    copyLink: '复制挑战链接',
    copied: '挑战链接已复制到剪贴板！',
    helpTitle: 'Snow Gloves OS · 操作手册',
    helpBody: '探索：使用 WASD / 方向键操纵成员，按 1–7 切换角色，按 E 与附近站点互动。选择 Overview 返回城镇总览；触屏方向键提供相同移动。手动行走仅为本地探索，工作状态来自连接的来源数据。\n\n沙盒：在玩具城中操纵怪兽。\n键位：WASD / 方向键移动，长按 Space 普攻，E 抓取/投掷，R 重踏，ESC 暂停。',
    close: '关闭',
    webglFail: 'WebGL 画布未能启动。当前启用纯数据降级视图。'
  }
};

const WALKTHROUGH_KEYS = ['hermes', 'chief-of-staff', 'interpreter', 'dispatcher', 'fleet', 'audit'];

function sanitizeSeed(raw: string | null): string {
  if (!raw) {
    const d = new Date();
    return `RUN_${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}${String(d.getUTCDate()).padStart(2, '0')}`;
  }
  const clean = raw.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
  return clean.length > 0 ? clean : 'DEFAULT_SEED';
}

function sanitizeCharacter(raw: string | null): CharacterId {
  if (raw === 'bongo' || raw === 'bolt') return raw;
  return 'munch';
}

const urlParams = new URLSearchParams(window.location.search);
const prefersMap = urlParams.get('view') === 'map';
const parsedBeat = Number(urlParams.get('beat'));
const challengeTarget = Number.isFinite(parsedBeat) && parsedBeat > 0 ? Math.floor(parsedBeat) : null;
let currentSeed = sanitizeSeed(urlParams.get('block') || urlParams.get('seed'));
let selectedCharacter: CharacterId = sanitizeCharacter(urlParams.get('character'));

let lang: Lang = 'en';
let activeTab: 'explore' | 'sandbox' = urlParams.get('mode') === 'sandbox' ? 'sandbox' : 'explore';
let activeLayer: Layer | 'all' = 'all';
let activeSearch = '';
let selectedNodeId: string | null = nodes[0]?.id || null;
let walkthroughIndex = 0;

const sound = new SoundEngine();
const replay = new ReplayRecorder();
let gameState: GameState = createGame(currentSeed, selectedCharacter);
let worldController: WorldController | null = null;
let cockpit: ReturnType<typeof mountCockpit> | null = null;
let home: ReturnType<typeof mountHome> | null = null;
let crewNavigation: CrewControlState = { slug: null, x: 0, z: 0, moving: false, nearbySlug: null };
let preferredCrewSlug = 'ceo';
function openOperations(nodeId?: string): void {
  if (gameState.mode === 'playing') { pause(gameState); clearInputs(); }
  cockpit?.open(nodeId);
}
let fieldKitReturnFocus: HTMLElement | null = null;
let fieldKitReturnFocusId = '';
function setFieldKitOpen(open: boolean): void {
  clearInputs();
  if (open && !document.body.classList.contains('field-kit-open')) {
    fieldKitReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    fieldKitReturnFocusId = fieldKitReturnFocus?.id || '';
  }
  document.body.classList.toggle('field-kit-open', open);
  home?.setKitOpen(open);
  document.querySelectorAll<HTMLElement>('.sg-sidebar, .sg-inspector').forEach(el => { el.inert = open; });
  document.getElementById('btn-operations')?.setAttribute('aria-expanded', String(open));
  if (!open) {
    canvasMount.dispatchEvent(new CustomEvent('world-focus', { detail: null }));
    const returnFocus = fieldKitReturnFocus?.isConnected ? fieldKitReturnFocus : document.getElementById(fieldKitReturnFocusId);
    if (returnFocus && !returnFocus.closest('[inert]')) returnFocus.focus();
    else document.getElementById('btn-operations')?.focus();
    fieldKitReturnFocus = null;
    fieldKitReturnFocusId = '';
  }
}
let lastFrameTime = performance.now();
let resultShownForRound = false;
let lastFocusedElement: HTMLElement | null = null;

const keyState = {
  KeyW: false,
  KeyA: false,
  KeyS: false,
  KeyD: false,
  ArrowUp: false,
  ArrowLeft: false,
  ArrowDown: false,
  ArrowRight: false,
  Space: false,
  touchX: 0,
  touchZ: 0,
  touchAttack: false
};

function clearInputs(): void {
  replay.pause();
  keyState.KeyW = false;
  keyState.KeyA = false;
  keyState.KeyS = false;
  keyState.KeyD = false;
  keyState.ArrowUp = false;
  keyState.ArrowLeft = false;
  keyState.ArrowDown = false;
  keyState.ArrowRight = false;
  keyState.Space = false;
  keyState.touchX = 0;
  keyState.touchZ = 0;
  keyState.touchAttack = false;
}

function editableElement(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && !!target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])');
}

function crewMayMove(target: EventTarget | null = document.activeElement, requireControl = true): boolean {
  return !!worldController && crewInputAllowed({
    explore: activeTab === 'explore',
    hasControl: requireControl ? !!home?.getControlledSlug() : true,
    hidden: document.hidden,
    dialog: !!document.querySelector('dialog[open]'),
    fieldKit: document.body.classList.contains('field-kit-open'),
    sourceNotes: document.body.classList.contains('source-notes-open'),
    encounter: document.body.classList.contains('home-encounter-open'),
    editable: editableElement(target)
  });
}

const app = document.getElementById('app') as HTMLElement;
if (!app) {
  throw new Error('#app root element missing');
}

app.innerHTML = `
  <header class="sg-header" role="banner">
    <div class="sg-brand">
      <span class="sg-logo-title">SNOW GLOVES</span>
      <span class="sg-slash">/</span>
      <span class="sg-subbrand" id="lbl-subbrand">${escapeHtml(i18n[lang].subBrand)}</span>
    </div>
    <nav class="sg-tabs" aria-label="Modes">
      <button type="button" class="sg-tab-btn ${activeTab === 'explore' ? 'active' : ''}" id="tab-explore">${escapeHtml(i18n[lang].explore)}</button>
      <button type="button" class="sg-tab-btn ${activeTab === 'sandbox' ? 'active' : ''}" id="tab-sandbox">${escapeHtml(i18n[lang].sandbox)}</button>
    </nav>
    <div class="sg-header-actions">
      <button type="button" class="sg-btn-ghost" id="btn-operations" aria-label="Open field kit" aria-expanded="false">FIELD KIT</button>
      <button type="button" class="sg-btn-ghost" id="btn-view">${prefersMap ? '3D CITY' : '2D MAP'}</button>
      <button type="button" class="sg-btn-ghost" id="btn-lang" aria-label="Toggle Language">${lang === 'en' ? '简中' : 'EN'}</button>
      <button type="button" class="sg-btn-ghost" id="btn-audio" aria-label="Toggle Audio">${sound.muted ? escapeHtml(i18n[lang].unmute) : escapeHtml(i18n[lang].mute)}</button>
      <button type="button" class="sg-btn-ghost" id="btn-help" aria-label="Open Help">${escapeHtml(i18n[lang].help)}</button>
    </div>
  </header>

  <div class="sg-body">
    <aside class="sg-sidebar" aria-label="Controls and Filter">
      <div class="sg-pane" id="pane-explore-controls" style="display:${activeTab === 'explore' ? 'block' : 'none'};">
        <div class="sg-side-section">
          <label class="sg-section-lbl" id="lbl-layers" for="layer-filter-select">${escapeHtml(i18n[lang].layers)}</label>
          <div class="sg-layer-pill-group" role="radiogroup" aria-label="Layer Filter">
            <button type="button" class="sg-pill active" data-layer="all">${escapeHtml(i18n[lang].allLayers)}</button>
            <button type="button" class="sg-pill" data-layer="strategy">Strategy</button>
            <button type="button" class="sg-pill" data-layer="knowledge">Knowledge</button>
            <button type="button" class="sg-pill" data-layer="orchestration">Orchestration</button>
            <button type="button" class="sg-pill" data-layer="governance">Governance</button>
            <button type="button" class="sg-pill" data-layer="runtime">Runtime</button>
          </div>
        </div>

        <div class="sg-side-section">
          <input type="search" id="sg-search-input" class="sg-input" placeholder="${escapeHtml(i18n[lang].searchPh)}" aria-label="Search nodes" />
        </div>

        <div class="sg-side-section">
          <div class="sg-section-lbl" id="lbl-walkthrough">${escapeHtml(i18n[lang].walkthrough)}</div>
          <div class="sg-btn-row">
            <button type="button" class="sg-btn" id="btn-wt-prev">&larr; ${escapeHtml(i18n[lang].prev)}</button>
            <button type="button" class="sg-btn" id="btn-wt-next">${escapeHtml(i18n[lang].next)} &rarr;</button>
          </div>
        </div>
      </div>

      <div class="sg-pane ${activeTab === 'sandbox' ? 'active' : ''}" id="pane-sandbox-controls" style="display: ${activeTab === 'sandbox' ? 'block' : 'none'};">
        <div class="sg-side-section">
          <label class="sg-section-lbl" id="lbl-character">${escapeHtml(i18n[lang].character)}</label>
          <select id="select-character" class="sg-select">
            <option value="munch" ${selectedCharacter === 'munch' ? 'selected' : ''}>${escapeHtml(i18n[lang].munch)}</option>
            <option value="bongo" ${selectedCharacter === 'bongo' ? 'selected' : ''}>${escapeHtml(i18n[lang].bongo)}</option>
            <option value="bolt" ${selectedCharacter === 'bolt' ? 'selected' : ''}>${escapeHtml(i18n[lang].bolt)}</option>
          </select>
        </div>
        <div class="sg-side-section">
          <button type="button" class="sg-btn sg-btn-primary" id="btn-start-round">${escapeHtml(i18n[lang].startRound)}</button>
        </div>
      </div>
    </aside>

    <main class="sg-stage-container" id="stage-container" role="region" aria-label="3D Infrastructure Viewport">
      <div class="sg-hero-watermark" aria-hidden="true">
        <h1 class="sg-hero-title" id="lbl-hero-title">${escapeHtml(i18n[lang].heroTitle)}</h1>
        <p class="sg-hero-sub" id="lbl-hero-sub">${escapeHtml(i18n[lang].heroSub)}</p>
      </div>

      <div id="sg-canvas-mount" class="sg-canvas-mount"></div>
      <div id="sg-webgl-fallback" class="sg-webgl-fallback" style="display:none;">
        <p id="lbl-webgl-fail">${escapeHtml(i18n[lang].webglFail)}</p>
      </div>

      <div class="sg-hud" id="sg-hud" style="display: ${activeTab === 'sandbox' ? 'flex' : 'none'};">
        <div class="sg-hud-card"><span class="sg-hud-lbl" id="lbl-hud-time">${escapeHtml(i18n[lang].time)}</span><span class="sg-hud-val" id="hud-val-time">45.0s</span></div>
        <div class="sg-hud-card"><span class="sg-hud-lbl" id="lbl-hud-score">${escapeHtml(i18n[lang].score)}</span><span class="sg-hud-val" id="hud-val-score">0</span></div>
        <div class="sg-hud-card"><span class="sg-hud-lbl" id="lbl-hud-destroyed">${escapeHtml(i18n[lang].destroyed)}</span><span class="sg-hud-val" id="hud-val-destroyed">0</span></div>
        <div class="sg-hud-card"><span class="sg-hud-lbl" id="lbl-hud-mult">${escapeHtml(i18n[lang].multiplier)}</span><span class="sg-hud-val" id="hud-val-mult">1.0x</span></div>
        <div class="sg-hud-card"><span class="sg-hud-lbl" id="lbl-hud-stomp">${escapeHtml(i18n[lang].stomp)}</span><span class="sg-hud-val" id="hud-val-stomp">READY</span></div>
        <button type="button" class="sg-btn" id="btn-hud-pause">${escapeHtml(i18n[lang].pause)}</button>
      </div>

      <div class="sg-touch-controls" id="sg-touch-controls" style="display:none;">
        <div class="sg-joystick-zone" id="sg-joystick-zone"><div class="sg-joystick-knob" id="sg-joystick-knob"></div></div>
        <div class="sg-touch-actions">
          <button type="button" class="sg-action-circle" id="btn-touch-attack">ATK</button>
          <button type="button" class="sg-action-circle" id="btn-touch-grab">E</button>
          <button type="button" class="sg-action-circle" id="btn-touch-stomp">R</button>
        </div>
      </div>
    </main>

    <aside class="sg-inspector" id="sg-inspector" aria-label="Node Contract Inspector">
      <div id="sg-inspector-content"></div>
    </aside>
  </div>

  <nav class="sg-bottom-navigator" aria-label="Topology nodes navigator">
    <div class="sg-nav-scroll" id="sg-nav-nodes" role="tablist"></div>
  </nav>

  <dialog id="dlg-help" class="sg-dialog" aria-labelledby="lbl-dlg-help-title">
    <div class="sg-dlg-inner">
      <h2 id="lbl-dlg-help-title" class="sg-dlg-title">${escapeHtml(i18n[lang].helpTitle)}</h2>
      <p id="lbl-dlg-help-body" class="sg-dlg-body" style="white-space: pre-line;">${escapeHtml(i18n[lang].helpBody)}</p>
      <div class="sg-dlg-footer">
        <button type="button" class="sg-btn sg-btn-primary" id="btn-help-close">${escapeHtml(i18n[lang].close)}</button>
      </div>
    </div>
  </dialog>

  <dialog id="dlg-pause" class="sg-dialog" aria-labelledby="lbl-dlg-pause-title">
    <div class="sg-dlg-inner">
      <h2 id="lbl-dlg-pause-title" class="sg-dlg-title">${escapeHtml(i18n[lang].paused)}</h2>
      <div class="sg-dlg-actions-stacked">
        <button type="button" class="sg-btn sg-btn-primary" id="btn-pause-resume">${escapeHtml(i18n[lang].resume)}</button>
        <button type="button" class="sg-btn" id="btn-pause-retry">${escapeHtml(i18n[lang].retry)}</button>
        <button type="button" class="sg-btn" id="btn-pause-home">${escapeHtml(i18n[lang].home)}</button>
      </div>
    </div>
  </dialog>

  <dialog id="dlg-result" class="sg-dialog" aria-labelledby="lbl-dlg-result-title">
    <div class="sg-dlg-inner">
      <h2 id="lbl-dlg-result-title" class="sg-dlg-title">${escapeHtml(i18n[lang].victory)}</h2>
      <div class="sg-result-stats">
        <div class="sg-stat-row"><span>${escapeHtml(i18n[lang].score)}</span><strong id="res-score">0</strong></div>
        <div class="sg-stat-row"><span>${escapeHtml(i18n[lang].destroyed)}</span><strong id="res-destroyed">0</strong></div>
        <div class="sg-stat-row"><span>${escapeHtml(i18n[lang].bestCombo)}</span><strong id="res-combo">0x</strong></div>
      </div>
      <div class="sg-dlg-actions-stacked">
        <button type="button" class="sg-btn sg-btn-primary" id="btn-res-retry">${escapeHtml(i18n[lang].retry)}</button>
        <button type="button" class="sg-btn" id="btn-res-export">${escapeHtml(i18n[lang].sharePng)}</button>
        <button type="button" class="sg-btn" id="btn-res-copy">${escapeHtml(i18n[lang].copyLink)}</button>
        ${typeof navigator.share === 'function' ? '<button type="button" class="sg-btn" id="btn-res-share">Share challenge…</button>' : ''}
        <button type="button" class="sg-btn" id="btn-res-home">${escapeHtml(i18n[lang].home)}</button>
      </div>
      <div id="sg-copy-toast" class="sg-copy-toast" style="display:none;">${escapeHtml(i18n[lang].copied)}</div>
      <label class="sg-section-lbl" for="challenge-link">Same block challenge URL</label>
      <input id="challenge-link" class="sg-search-input" type="text" readonly aria-label="Challenge URL, select and copy manually" />
      <p id="challenge-status" class="sg-insp-detail" role="status"></p>
    </div>
  </dialog>
`;

const canvasMount = document.getElementById('sg-canvas-mount') as HTMLElement;
const fallbackMount = document.getElementById('sg-webgl-fallback') as HTMLElement;
const dlgHelp = document.getElementById('dlg-help') as HTMLDialogElement;
const dlgPause = document.getElementById('dlg-pause') as HTMLDialogElement;
const dlgResult = document.getElementById('dlg-result') as HTMLDialogElement;
const inspectorContent = document.getElementById('sg-inspector-content') as HTMLElement;
const navNodes = document.getElementById('sg-nav-nodes') as HTMLElement;
const hudValTime = document.getElementById('hud-val-time') as HTMLElement;
const hudValScore = document.getElementById('hud-val-score') as HTMLElement;
const hudValDestroyed = document.getElementById('hud-val-destroyed') as HTMLElement;
const hudValMult = document.getElementById('hud-val-mult') as HTMLElement;
const hudValStomp = document.getElementById('hud-val-stomp') as HTMLElement;

function openDialog(dlg: HTMLDialogElement): void {
  if (dlg.open) return;
  lastFocusedElement = document.activeElement as HTMLElement;
  if (typeof dlg.showModal === 'function') {
    dlg.showModal();
  } else {
    dlg.setAttribute('open', 'true');
  }
}

function closeDialog(dlg: HTMLDialogElement): void {
  if (typeof dlg.close === 'function') {
    dlg.close();
  } else {
    dlg.removeAttribute('open');
  }
  if (lastFocusedElement) {
    lastFocusedElement.focus();
  }
}

try {
  if (prefersMap) throw new Error('Accessible map view selected');
  worldController = createWorld(canvasMount, nodes, gameState, (id: string) => {
    selectedNodeId = id;
    renderInspector();
    renderNavigator();
    worldController?.select(id);
    if (id.startsWith('agent-')) home?.selectResident(id.slice(6));
  });
} catch (e) {
  document.body.classList.add('home-flat-map');
  if (!prefersMap) console.warn('WebGL init failed; using fallback view', e);
  if (fallbackMount) fallbackMount.style.display = 'block';
}

function getFilteredNodes() {
  return nodes.filter(n => {
    const matchLayer = activeLayer === 'all' || n.layer === activeLayer;
    const q = activeSearch.trim().toLowerCase();
    const matchQuery = !q || n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || n.short.toLowerCase().includes(q);
    return matchLayer && matchQuery;
  });
}

function renderNavigator(): void {
  const filtered = getFilteredNodes();
  if (!worldController && fallbackMount) {
    fallbackMount.innerHTML = `<div class="sg-map-view"><p>${prefersMap ? 'Accessible source map · 3D rendering disabled by preference' : escapeHtml(i18n[lang].webglFail)}</p><div class="sg-map-grid">${filtered.map(n => `<button class="sg-map-node" data-map-id="${escapeHtml(n.id)}" aria-pressed="${n.id === selectedNodeId}"><span style="background:${escapeHtml(n.color)}"></span>${escapeHtml(n.name)}<small>${escapeHtml(n.layer)}</small></button>`).join('')}</div></div>`;
    fallbackMount.querySelectorAll<HTMLButtonElement>('[data-map-id]').forEach(b => b.onclick = () => {
      selectedNodeId = b.dataset.mapId || null; renderInspector(); renderNavigator();
      if (selectedNodeId?.startsWith('agent-')) home?.selectResident(selectedNodeId.slice(6));
      else if (selectedNodeId) openOperations(selectedNodeId);
    });
  }
  navNodes.innerHTML = filtered.map((n, idx) => {
    const isSelected = n.id === selectedNodeId;
    return `
      <button type="button"
        role="tab"
        class="sg-nav-item ${isSelected ? 'selected' : ''}"
        data-id="${escapeHtml(n.id)}"
        aria-selected="${isSelected ? 'true' : 'false'}"
        aria-pressed="${isSelected ? 'true' : 'false'}"
        style="--item-color: ${escapeHtml(n.color)}">
        <span class="sg-nav-num">${String(idx + 1).padStart(2, '0')}</span>
        <span class="sg-nav-tag">${escapeHtml(n.short)}</span>
        <span class="sg-nav-name">${escapeHtml(n.name)}</span>
      </button>
    `;
  }).join('');

  navNodes.querySelectorAll('.sg-nav-item').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const id = (e.currentTarget as HTMLElement).getAttribute('data-id');
      if (id) {
        selectedNodeId = id;
        worldController?.select(id);
        renderInspector();
        renderNavigator();
      }
    });
  });
}

function renderInspector(): void {
  const node = nodes.find(n => n.id === selectedNodeId);
  if (!node) {
    inspectorContent.innerHTML = `<div class="sg-inspector-empty">${escapeHtml(i18n[lang].inspectorEmpty)}</div>`;
    return;
  }

  const relatedNodes = nodes.filter(n => node.links && node.links.includes(n.id));

  inspectorContent.innerHTML = `
    <div class="sg-insp-header" style="border-left: 4px solid ${escapeHtml(node.color)};">
      <div class="sg-insp-layer">${escapeHtml(node.layer.toUpperCase())}</div>
      <h2 class="sg-insp-title">${escapeHtml(node.name)}</h2>
      <div class="sg-insp-badge badge-${escapeHtml(node.evidence)}">${escapeHtml(node.evidence.toUpperCase())} AUDIT</div>
    </div>
    <p class="sg-insp-summary">${escapeHtml(node.summary)}</p>
    <p class="sg-insp-detail">${escapeHtml(node.detail)}</p>
    <button type="button" class="sg-btn sg-btn-primary" id="btn-inspector-workspace">Open workspace</button>
    <div class="sg-insp-section">
      <div class="sg-insp-sec-title">${escapeHtml(i18n[lang].evidenceNote)}</div>
      <p class="sg-insp-detail">${escapeHtml(node.evidenceNote || node.detail)}</p>
    </div>
    <div class="sg-insp-section">
      <div class="sg-insp-sec-title">${escapeHtml(i18n[lang].sources)}</div>
      <ul class="sg-insp-paths">
        ${node.sources.map((s, index) => `<li><button type="button" class="sg-btn-link" id="btn-inspector-source-${escapeHtml(node.id)}-${index}" data-source-document="${escapeHtml(s)}"><code>${escapeHtml(s)}</code></button></li>`).join('')}
      </ul>
    </div>
    <div class="sg-insp-section">
      <div class="sg-insp-sec-title">${escapeHtml(i18n[lang].relations)}</div>
      <div class="sg-relation-group">
        ${relatedNodes.map(r => `
          <button type="button" class="sg-btn-link" data-target="${escapeHtml(r.id)}" style="border-color:${escapeHtml(r.color)}">
            ${escapeHtml(r.name)}
          </button>
        `).join('') || '<span class="sg-muted">None</span>'}
      </div>
    </div>
  `;

  inspectorContent.querySelectorAll('.sg-btn-link').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const target = (e.currentTarget as HTMLElement).getAttribute('data-target');
      if (target) {
        selectedNodeId = target;
        worldController?.select(target);
        renderInspector();
        renderNavigator();
      }
    });
  });
  inspectorContent.querySelector<HTMLButtonElement>('#btn-inspector-workspace')!.onclick = () => openOperations(node.id);
  inspectorContent.querySelectorAll<HTMLButtonElement>('[data-source-document]').forEach(b => b.onclick = () => {
    if (gameState.mode === 'playing') { pause(gameState); clearInputs(); }
    cockpit?.openDocument(b.dataset.sourceDocument!);
  });
}

function updateLocaleUI(): void {
  const l = i18n[lang];
  const subbrand = document.getElementById('lbl-subbrand');
  if (subbrand) subbrand.textContent = l.subBrand;
  const tabExp = document.getElementById('tab-explore');
  if (tabExp) tabExp.textContent = l.explore;
  const tabSnd = document.getElementById('tab-sandbox');
  if (tabSnd) tabSnd.textContent = l.sandbox;
  const btnAud = document.getElementById('btn-audio');
  if (btnAud) btnAud.textContent = sound.muted ? l.unmute : l.mute;
  const btnHlp = document.getElementById('btn-help');
  if (btnHlp) btnHlp.textContent = l.help;
  const btnLng = document.getElementById('btn-lang');
  if (btnLng) btnLng.textContent = lang === 'en' ? '简中' : 'EN';
  const heroT = document.getElementById('lbl-hero-title');
  if (heroT) heroT.textContent = l.heroTitle;
  const heroS = document.getElementById('lbl-hero-sub');
  if (heroS) heroS.textContent = l.heroSub;
  const lblLay = document.getElementById('lbl-layers');
  if (lblLay) lblLay.textContent = l.layers;
  const sInp = document.getElementById('sg-search-input') as HTMLInputElement;
  if (sInp) sInp.placeholder = l.searchPh;
  const lblWt = document.getElementById('lbl-walkthrough');
  if (lblWt) lblWt.textContent = l.walkthrough;
  const btnWtP = document.getElementById('btn-wt-prev');
  if (btnWtP) btnWtP.innerHTML = `&larr; ${escapeHtml(l.prev)}`;
  const btnWtN = document.getElementById('btn-wt-next');
  if (btnWtN) btnWtN.innerHTML = `${escapeHtml(l.next)} &rarr;`;
  const lblChar = document.getElementById('lbl-character');
  if (lblChar) lblChar.textContent = l.character;
  const btnStart = document.getElementById('btn-start-round');
  if (btnStart) btnStart.textContent = l.startRound;
  const hTime = document.getElementById('lbl-hud-time');
  if (hTime) hTime.textContent = l.time;
  const hScore = document.getElementById('lbl-hud-score');
  if (hScore) hScore.textContent = l.score;
  const hDest = document.getElementById('lbl-hud-destroyed');
  if (hDest) hDest.textContent = l.destroyed;
  const hMult = document.getElementById('lbl-hud-multiplier');
  if (hMult) hMult.textContent = l.multiplier;
  const hStomp = document.getElementById('lbl-hud-stomp');
  if (hStomp) hStomp.textContent = l.stomp;
  const hPause = document.getElementById('btn-hud-pause');
  if (hPause) hPause.textContent = l.pause;
  const dlgHlpT = document.getElementById('lbl-dlg-help-title');
  if (dlgHlpT) dlgHlpT.textContent = l.helpTitle;
  const dlgHlpB = document.getElementById('lbl-dlg-help-body');
  if (dlgHlpB) dlgHlpB.textContent = l.helpBody;
  const dlgHlpC = document.getElementById('btn-help-close');
  if (dlgHlpC) dlgHlpC.textContent = l.close;
  const dlgPauT = document.getElementById('lbl-dlg-pause-title');
  if (dlgPauT) dlgPauT.textContent = l.paused;
  const btnRes = document.getElementById('btn-pause-resume');
  if (btnRes) btnRes.textContent = l.resume;
  const btnRet = document.getElementById('btn-pause-retry');
  if (btnRet) btnRet.textContent = l.retry;
  const btnHom = document.getElementById('btn-pause-home');
  if (btnHom) btnHom.textContent = l.home;
  const btnResRet = document.getElementById('btn-res-retry');
  if (btnResRet) btnResRet.textContent = l.retry;
  const btnResExp = document.getElementById('btn-res-export');
  if (btnResExp) btnResExp.textContent = l.sharePng;
  const btnResCpy = document.getElementById('btn-res-copy');
  if (btnResCpy) btnResCpy.textContent = l.copyLink;
  const btnResHom = document.getElementById('btn-res-home');
  if (btnResHom) btnResHom.textContent = l.home;
  renderInspector();
  renderNavigator();
}

document.getElementById('btn-lang')?.addEventListener('click', () => {
  lang = lang === 'en' ? 'zh' : 'en';
  updateLocaleUI();
});

document.getElementById('btn-audio')?.addEventListener('click', () => {
  sound.unlock();
  const muted = sound.toggle();
  const btn = document.getElementById('btn-audio');
  if (btn) {
    btn.textContent = muted ? escapeHtml(i18n[lang].unmute) : escapeHtml(i18n[lang].mute);
  }
});

document.getElementById('btn-help')?.addEventListener('click', () => {
  if (gameState.mode === 'playing') { pause(gameState); clearInputs(); }
  openDialog(dlgHelp);
});
document.getElementById('btn-view')?.addEventListener('click', () => {
  const url = new URL(window.location.href);
  if (prefersMap) url.searchParams.delete('view'); else url.searchParams.set('view', 'map');
  window.location.assign(url.toString());
});
document.getElementById('btn-help-close')?.addEventListener('click', () => {
  closeDialog(dlgHelp);
  if (gameState.mode === 'paused') openDialog(dlgPause);
});

const tabExplore = document.getElementById('tab-explore') as HTMLElement;
const tabSandbox = document.getElementById('tab-sandbox') as HTMLElement;
const paneExplore = document.getElementById('pane-explore-controls') as HTMLElement;
const paneSandbox = document.getElementById('pane-sandbox-controls') as HTMLElement;
const hud = document.getElementById('sg-hud') as HTMLElement;

function switchTab(mode: 'explore' | 'sandbox'): void {
  clearInputs();
  activeTab = mode;
  canvasMount.setAttribute('aria-label', !worldController ? 'Accessible infrastructure source map. Select a landmark or crew portrait to inspect its source.' : mode === 'explore'
    ? 'Infrastructure town. WASD or arrows to walk, one through seven to switch crew, E to meet a nearby station.'
    : 'Monster sandbox. WASD or arrows to move, Space to attack, E to grab or throw, R to stomp.');
  document.body.classList.toggle('home-explore', mode === 'explore');
  home?.setVisible(mode === 'explore');
  canvasMount.dispatchEvent(new CustomEvent('resident-visible', { detail: mode === 'explore' }));
  if (mode === 'explore') {
    tabExplore.classList.add('active');
    tabSandbox.classList.remove('active');
    paneExplore.style.display = 'block';
    paneSandbox.style.display = 'none';
    hud.style.display = 'none';
    if (gameState.mode === 'playing') {
      pause(gameState);
    }
    gameState = createGame(currentSeed, selectedCharacter);
    worldController?.reset(gameState);
    if (worldController) home?.walkAsResident(preferredCrewSlug);
    document.getElementById('sg-touch-controls')!.style.display = 'none';
  } else {
    tabSandbox.classList.add('active');
    tabExplore.classList.remove('active');
    paneExplore.style.display = 'none';
    paneSandbox.style.display = 'block';
    hud.style.display = 'flex';
  }
}

tabExplore?.addEventListener('click', () => switchTab('explore'));
tabSandbox?.addEventListener('click', () => switchTab('sandbox'));

document.querySelectorAll('.sg-layer-pill-group .sg-pill').forEach(pill => {
  pill.addEventListener('click', (e) => {
    document.querySelectorAll('.sg-layer-pill-group .sg-pill').forEach(p => p.classList.remove('active'));
    const target = e.currentTarget as HTMLElement;
    target.classList.add('active');
    const layer = (target.getAttribute('data-layer') || 'all') as Layer | 'all';
    activeLayer = layer;
    worldController?.filter(layer);
    renderNavigator();
  });
});

document.getElementById('sg-search-input')?.addEventListener('input', (e) => {
  activeSearch = (e.target as HTMLInputElement).value;
  renderNavigator();
});

function triggerWalkthrough(dir: number): void {
  activeLayer = 'all';
  activeSearch = '';
  const search = document.getElementById('sg-search-input') as HTMLInputElement;
  search.value = '';
  document.querySelectorAll('.sg-layer-pill-group .sg-pill').forEach(p => p.classList.toggle('active', p.getAttribute('data-layer') === 'all'));
  worldController?.filter('all');
  const matches = WALKTHROUGH_KEYS.map(k => nodes.find(n => n.id.toLowerCase().includes(k) || n.name.toLowerCase().includes(k) || (k === 'audit' && n.id.includes('sentinel')))).filter((n): n is typeof nodes[number] => !!n);
  if (matches.length === 0) return;
  walkthroughIndex = (walkthroughIndex + dir + matches.length) % matches.length;
  const target = matches[walkthroughIndex];
  selectedNodeId = target.id;
  worldController?.select(target.id);
  canvasMount.dispatchEvent(new CustomEvent('world-focus', { detail: target.id }));
  worldController?.route(matches.map(m => m.id));
  renderInspector();
  renderNavigator();
}

document.getElementById('btn-wt-prev')?.addEventListener('click', () => triggerWalkthrough(-1));
document.getElementById('btn-wt-next')?.addEventListener('click', () => triggerWalkthrough(1));

const selectCharacter = document.getElementById('select-character') as HTMLSelectElement;
selectCharacter?.addEventListener('change', (e) => {
  selectedCharacter = (e.target as HTMLSelectElement).value as CharacterId;
  gameState = createGame(currentSeed, selectedCharacter);
  worldController?.reset(gameState);
});

function startSimulation(): void {
  clearInputs();
  sound.unlock();
  resultShownForRound = false;
  gameState = createGame(currentSeed, selectedCharacter);
  start(gameState);
  worldController?.reset(gameState);
  replay.start(canvasMount.querySelector('canvas'));
  if (window.matchMedia('(pointer: coarse)').matches) {
    const tc = document.getElementById('sg-touch-controls');
    if (tc) tc.style.display = 'flex';
  }
}

document.getElementById('btn-start-round')?.addEventListener('click', startSimulation);

document.getElementById('btn-hud-pause')?.addEventListener('click', () => {
  if (gameState.mode === 'playing') {
    pause(gameState);
    clearInputs();
    openDialog(dlgPause);
  }
});

document.getElementById('btn-pause-resume')?.addEventListener('click', () => {
  if (gameState.mode === 'paused') {
    resume(gameState);
  }
  closeDialog(dlgPause);
});

document.getElementById('btn-pause-retry')?.addEventListener('click', () => {
  closeDialog(dlgPause);
  startSimulation();
});

document.getElementById('btn-pause-home')?.addEventListener('click', () => {
  closeDialog(dlgPause);
  switchTab('explore');
});

document.getElementById('btn-res-retry')?.addEventListener('click', () => {
  closeDialog(dlgResult);
  startSimulation();
});

document.getElementById('btn-res-export')?.addEventListener('click', () => {
  exportScorecard(gameState);
});

document.getElementById('btn-res-copy')?.addEventListener('click', () => {
  const url = challengeUrl(gameState);
  const input = document.getElementById('challenge-link') as HTMLInputElement;
  const status = document.getElementById('challenge-status')!;
  input.value = url;
  input.focus(); input.select();
  if (!navigator.clipboard?.writeText) { status.textContent = 'Select and copy the challenge URL above.'; return; }
  navigator.clipboard.writeText(url).then(() => {
    status.textContent = lang === 'zh' ? '挑战链接已复制。' : 'Challenge link copied.';
    const toast = document.getElementById('sg-copy-toast');
    if (toast) {
      toast.style.display = 'block';
      setTimeout(() => { toast.style.display = 'none'; }, 2000);
    }
  }).catch(() => { input.focus(); input.select(); status.textContent = lang === 'zh' ? '请手动复制上方链接。' : 'Clipboard unavailable here. Select and copy the challenge URL above.'; });
});

document.getElementById('btn-res-home')?.addEventListener('click', () => {
  closeDialog(dlgResult);
  switchTab('explore');
});
document.getElementById('btn-res-share')?.addEventListener('click', () => {
  const url = challengeUrl(gameState);
  void navigator.share({ title: 'Snow Gloves · Same block challenge', text: `Try this simulated city block. My score: ${gameState.score}.`, url }).catch(() => {
    const input = document.getElementById('challenge-link') as HTMLInputElement;
    input.value = url; input.focus(); input.select();
    document.getElementById('challenge-status')!.textContent = 'Select and copy the challenge URL, or try Copy Challenge Link.';
  });
});

window.addEventListener('keydown', (e: KeyboardEvent) => {
  if (activeTab === 'explore') {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || !crewMayMove(e.target, false)) return;
    const crewIndex = /^Digit[1-7]$/.test(e.code) ? Number(e.code.slice(5)) - 1 : -1;
    if (crewIndex >= 0 && !e.repeat) {
      e.preventDefault(); clearInputs(); home?.walkAsResident(RESIDENTS[crewIndex].slug); return;
    }
    if (!crewMayMove(e.target)) return;
    if (e.code === 'KeyE' && !e.repeat) {
      e.preventDefault(); clearInputs();
      if (crewNavigation.nearbySlug) home?.selectResident(crewNavigation.nearbySlug);
      return;
    }
    if (/^(Key[WASD]|Arrow(Up|Down|Left|Right))$/.test(e.code)) {
      // Arrow keys retain native button/toolbar navigation; WASD works from the crew belt.
      if (e.code.startsWith('Arrow') && (e.target as HTMLElement)?.closest('button, [role="toolbar"], [role="tablist"]')) return;
      e.preventDefault(); (keyState as Record<string, boolean | number>)[e.code] = true;
    }
    return;
  }
  if ((e.target as HTMLElement)?.closest('.oc-cockpit, .oc-nav, .oc-dialog, .ih-home-root')) return;
  if (document.body.classList.contains('field-kit-open') && e.code === 'Escape') return;
  const tag = (e.target as HTMLElement)?.tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;

  if (e.code === 'Escape') {
    if (dlgHelp.open) return;
    e.preventDefault();
    if (gameState.mode === 'playing') {
      pause(gameState);
      clearInputs();
      openDialog(dlgPause);
    } else if (gameState.mode === 'paused') {
      resume(gameState);
      closeDialog(dlgPause);
    }
    return;
  }

  if (gameState.mode !== 'playing') return;
  if (['Space','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)) e.preventDefault();

  if (e.code === 'KeyE') {
    sound.unlock();
    const events = grabThrow(gameState);
    events.forEach(ev => { sound.play(ev); worldController?.event(ev); });
    return;
  }
  if (e.code === 'KeyR') {
    sound.unlock();
    const events = stomp(gameState);
    events.forEach(ev => { sound.play(ev); worldController?.event(ev); });
    return;
  }

  if (e.code in keyState) {
    (keyState as Record<string, boolean | number>)[e.code] = true;
  }
});

window.addEventListener('keyup', (e: KeyboardEvent) => {
  if (e.code in keyState) {
    (keyState as Record<string, boolean | number>)[e.code] = false;
  }
});

window.addEventListener('blur', () => {
  clearInputs();
  if (gameState.mode === 'playing') { pause(gameState); openDialog(dlgPause); }
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearInputs();
    if (gameState.mode === 'playing') {
      pause(gameState);
      openDialog(dlgPause);
    }
  }
});

const joystickZone = document.getElementById('sg-joystick-zone');
const joystickKnob = document.getElementById('sg-joystick-knob');
let joystickActive = false;
let joyStart = { x: 0, y: 0 };

joystickZone?.addEventListener('pointerdown', (e: PointerEvent) => {
  joystickActive = true;
  joystickZone.setPointerCapture(e.pointerId);
  joyStart = { x: e.clientX, y: e.clientY };
});

joystickZone?.addEventListener('pointermove', (e: PointerEvent) => {
  if (!joystickActive) return;
  const dx = e.clientX - joyStart.x;
  const dy = e.clientY - joyStart.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const maxDist = 40;
  const clamped = Math.min(dist, maxDist);
  const angle = Math.atan2(dy, dx);
  const kx = Math.cos(angle) * clamped;
  const ky = Math.sin(angle) * clamped;

  if (joystickKnob) {
    joystickKnob.style.transform = `translate(${kx}px, ${ky}px)`;
  }
  keyState.touchX = kx / maxDist;
  keyState.touchZ = ky / maxDist;
});

const endJoystick = (e: PointerEvent) => {
  if (!joystickActive) return;
  joystickActive = false;
  try { joystickZone?.releasePointerCapture(e.pointerId); } catch {} 
  if (joystickKnob) joystickKnob.style.transform = 'translate(0px, 0px)';
  keyState.touchX = 0;
  keyState.touchZ = 0;
};

joystickZone?.addEventListener('pointerup', endJoystick);
joystickZone?.addEventListener('pointercancel', endJoystick);

const btnTouchAtk = document.getElementById('btn-touch-attack');
btnTouchAtk?.addEventListener('pointerdown', () => { keyState.touchAttack = true; sound.unlock(); });
btnTouchAtk?.addEventListener('pointerup', () => { keyState.touchAttack = false; });
btnTouchAtk?.addEventListener('pointercancel', () => { keyState.touchAttack = false; });

document.getElementById('btn-touch-grab')?.addEventListener('click', () => {
  if (gameState.mode === 'playing') {
    sound.unlock();
    const events = grabThrow(gameState);
    events.forEach(ev => { sound.play(ev); worldController?.event(ev); });
  }
});

document.getElementById('btn-touch-stomp')?.addEventListener('click', () => {
  if (gameState.mode === 'playing') {
    sound.unlock();
    const events = stomp(gameState);
    events.forEach(ev => { sound.play(ev); worldController?.event(ev); });
  }
});

function mainLoop(now: number): void {
  const dt = Math.min((now - lastFrameTime) / 1000, 0.1);
  lastFrameTime = now;

  if (activeTab === 'explore' && worldController) {
    const allowed = crewMayMove();
    if (!allowed) clearInputs();
    const moveX = allowed ? Number(keyState.KeyD || keyState.ArrowRight) - Number(keyState.KeyA || keyState.ArrowLeft) + keyState.touchX : 0;
    const moveZ = allowed ? Number(keyState.KeyS || keyState.ArrowDown) - Number(keyState.KeyW || keyState.ArrowUp) + keyState.touchZ : 0;
    crewNavigation = worldController.moveResident(moveX, moveZ, dt);
    home?.setNavigation(crewNavigation);
  }

  if (gameState.mode === 'playing') {
    let moveX = 0;
    let moveZ = 0;
    if (keyState.KeyW || keyState.ArrowUp) moveZ -= 1;
    if (keyState.KeyS || keyState.ArrowDown) moveZ += 1;
    if (keyState.KeyA || keyState.ArrowLeft) moveX -= 1;
    if (keyState.KeyD || keyState.ArrowRight) moveX += 1;

    if (keyState.touchX !== 0 || keyState.touchZ !== 0) {
      moveX = keyState.touchX;
      moveZ = keyState.touchZ;
    } else {
      const len = Math.sqrt(moveX * moveX + moveZ * moveZ);
      if (len > 0) {
        moveX /= len;
        moveZ /= len;
      }
    }

    const attackHeld = keyState.Space || keyState.touchAttack;
    const events = tick(gameState, dt, { x: moveX, z: moveZ, attack: attackHeld });

    events.forEach(ev => {
      sound.play(ev);
      worldController?.event(ev);
    });

    if (hudValTime) hudValTime.textContent = `${Math.max(0, gameState.remaining).toFixed(1)}s`;
    if (hudValScore) hudValScore.textContent = `${gameState.score}`;
    if (hudValDestroyed) hudValDestroyed.textContent = `${gameState.destroyed}`;
    if (hudValMult) hudValMult.textContent = `${gameState.multiplier.toFixed(1)}x`;
    if (hudValStomp) {
      hudValStomp.textContent = gameState.stompCooldown <= 0 ? 'READY' : `${gameState.stompCooldown.toFixed(1)}s`;
    }

  }

    if (gameState.mode === 'result' && !resultShownForRound) {
      resultShownForRound = true;
      clearInputs();
      const resScore = document.getElementById('res-score');
      const resDest = document.getElementById('res-destroyed');
      const resCombo = document.getElementById('res-combo');
      if (resScore) resScore.textContent = `${gameState.score}`;
      if (resDest) resDest.textContent = `${gameState.destroyed}`;
      if (resCombo) resCombo.textContent = `${gameState.bestCombo}x`;
      if (resCombo) resCombo.textContent = String(gameState.bestCombo);
      openDialog(dlgResult);
      (document.getElementById('challenge-link') as HTMLInputElement).value = challengeUrl(gameState);
      void replay.stop().then(() => {
        const old = document.getElementById('btn-res-replay');
        old?.remove();
        const button = document.createElement('button');
        button.id = 'btn-res-replay';
        button.className = 'sg-btn';
        button.textContent = replay.available ? (lang === 'zh' ? '下载模拟录像' : 'Download replay') : (lang === 'zh' ? '浏览器不支持录像' : 'Replay recording unavailable in this browser');
        button.disabled = !replay.available;
        button.onclick = () => replay.download(gameState.seed);
        document.getElementById('btn-res-export')?.after(button);
      });
    }
  worldController?.update(gameState, dt);
  if (gameState.mode === 'playing') replay.resume(); else replay.pause();
  requestAnimationFrame(mainLoop);
}

const operationsHost = document.createElement('div');
document.body.append(operationsHost);
cockpit = mountCockpit(operationsHost, id => {
  if (!nodes.some(n => n.id === id)) return;
  activeLayer = 'all'; activeSearch = '';
  worldController?.filter('all');
  selectedNodeId = id; worldController?.select(id);
  canvasMount.dispatchEvent(new CustomEvent('world-focus', { detail: id }));
  renderInspector(); renderNavigator();
});
operationsHost.addEventListener('cockpit-open', () => setFieldKitOpen(true));
operationsHost.addEventListener('cockpit-station', event => {
  const id = (event as CustomEvent<{ nodeId?: string }>).detail?.nodeId;
  if (!id || !nodes.some(node => node.id === id)) return;
  selectedNodeId = id;
  worldController?.filter('all');
  worldController?.select(id);
  canvasMount.dispatchEvent(new CustomEvent('world-focus', { detail: id }));
  renderInspector(); renderNavigator();
});
operationsHost.addEventListener('cockpit-close', () => {
  setFieldKitOpen(false);
  if (gameState.mode === 'paused') openDialog(dlgPause);
});
document.getElementById('btn-operations')!.onclick = () => openOperations();
const notesReturn = document.createElement('button');
notesReturn.type = 'button'; notesReturn.className = 'ih-notes-return ih-btn'; notesReturn.textContent = 'Back to crew';
notesReturn.onclick = () => document.querySelector<HTMLButtonElement>('#ih-btn-notes-toggle')?.click();
document.querySelector('.sg-sidebar')?.prepend(notesReturn);
const homeHost = document.createElement('div');
document.body.append(homeHost);
function focusHomeNode(id: string): void {
  if (!nodes.some(node => node.id === id)) return;
  activeLayer = 'all'; activeSearch = '';
  document.querySelector<HTMLInputElement>('#sg-search-input')!.value = '';
  document.querySelectorAll<HTMLButtonElement>('[data-layer]').forEach(button => button.classList.toggle('active', button.dataset.layer === 'all'));
  selectedNodeId = id;
  worldController?.filter('all'); worldController?.select(id);
  canvasMount.dispatchEvent(new CustomEvent('world-focus', { detail: id }));
  renderInspector(); renderNavigator();
}
home = mountHome(homeHost, {
  focusNode: focusHomeNode,
  openAgent: id => openOperations(id),
  openDocument: path => { setFieldKitOpen(true); void cockpit?.openDocument(path); },
  toggleNotes: open => { clearInputs(); document.body.classList.toggle('source-notes-open', open); },
  onPresence: presence => canvasMount.dispatchEvent(new CustomEvent('resident-presence', { detail: presence })),
  followTour: () => { triggerWalkthrough(1); },
  openBlueprint: () => { openOperations(); document.querySelector<HTMLButtonElement>('#oc-nav-tab-workbench')?.click(); },
  controlResident: slug => {
    if (slug && RESIDENTS.some(resident => resident.slug === slug)) preferredCrewSlug = slug;
    clearInputs(); worldController?.controlResident(slug);
    crewNavigation = worldController?.moveResident(0, 0, 0) || { slug: null, x: 0, z: 0, moving: false, nearbySlug: null };
    home?.setNavigation(crewNavigation);
  },
  moveInput: (x, z) => { keyState.touchX = x; keyState.touchZ = z; },
});
canvasMount.addEventListener('resident-select', event => home?.selectResident((event as CustomEvent<{slug:string}>).detail.slug));
document.body.classList.toggle('home-explore', activeTab === 'explore');
home.setVisible(activeTab === 'explore');
canvasMount.tabIndex = 0;
canvasMount.setAttribute('aria-label', !worldController ? 'Accessible infrastructure source map. Select a landmark or crew portrait to inspect its source.' : activeTab === 'explore'
  ? 'Infrastructure town. WASD or arrows to walk, one through seven to switch crew, E to meet a nearby station.'
  : 'Monster sandbox. WASD or arrows to move, Space to attack, E to grab or throw, R to stomp.');
if (activeTab === 'explore' && worldController) home.walkAsResident('ceo');
canvasMount.dispatchEvent(new CustomEvent('resident-visible', { detail: activeTab === 'explore' }));
renderInspector();
renderNavigator();
worldController?.select(selectedNodeId);
if (challengeTarget) {
  const hint = document.createElement('p');
  hint.className = 'sg-section-lbl';
  hint.textContent = `Same block challenge · Beat ${challengeTarget.toLocaleString()} points`;
  paneSandbox.append(hint);
}
dlgPause.addEventListener('cancel', e => e.preventDefault());
dlgResult.addEventListener('cancel', e => e.preventDefault());
dlgHelp.addEventListener('close', () => { if (gameState.mode === 'paused' && !dlgPause.open) openDialog(dlgPause); });
window.addEventListener('beforeunload', () => { clearInputs(); replay.dispose(); home?.dispose(); worldController?.dispose(); });
requestAnimationFrame(mainLoop);
if (prefersMap) {
  document.getElementById('btn-start-round')!.setAttribute('disabled', '');
  document.getElementById('btn-start-round')!.textContent = 'Use 3D City for sandbox play';
}
