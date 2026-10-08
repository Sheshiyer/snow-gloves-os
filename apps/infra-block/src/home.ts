import './home.css';
import {
  RESIDENTS,
  derivePresence,
  demoPresence,
  type ResidentSlug,
  type ResidentPresence
} from './residents';
import type { OpsSnapshot } from './ops-contracts';
import { loadSnapshot, validateSnapshot } from './ops-client';

export interface MountHomeCallbacks {
  focusNode(id: string): void;
  openAgent(id: string): void;
  openDocument(path: string): void;
  toggleNotes(open: boolean): void;
  onPresence(presence: ResidentPresence[]): void;
  followTour(): void;
  openBlueprint(): void;
}

export interface HomeHandle {
  setVisible(visible: boolean):
    void;
  setKitOpen(open: boolean): void;
  selectResident(slug: string): void;
  dispose(): void;
}

interface ProjectionState {
  snapshot: OpsSnapshot | null;
  scopeMode: 'public-fixtures' | 'local-private' | null;
  tenant: string | null;
  source: 'api' | 'fixture' | 'unavailable';
  stale: boolean;
  lastUpdatedMs: number | null;
  label: string;
}

function getFixedPortraitSvg(slug: ResidentSlug): string {
  switch (slug) {
    case 'ceo':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#f5eedc"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#e5d5b7" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M28 32 Q32 35 36 32" stroke="#283d36" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#d5b466" stroke="#283d36" stroke-width="2"/>
        <circle cx="44" cy="46" r="8" fill="#ffffff" stroke="#283d36" stroke-width="1.8"/>
        <polygon points="44,40 46,45 44,44 42,45" fill="#c97858"/>
        <polygon points="44,52 46,47 44,48 42,47" fill="#699a92"/>
        <circle cx="44" cy="46" r="1.5" fill="#283d36"/>
      </svg>`;
    case 'cto':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#e8f1f5"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#c8dbe6" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M29 32 L35 32" stroke="#283d36" stroke-width="1.5" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#4d7c9e" stroke="#283d36" stroke-width="2"/>
        <rect x="36" y="42" width="16" height="14" rx="2" fill="#28536b" stroke="#ffffff" stroke-width="1.2"/>
        <line x1="39" y1="46" x2="49" y2="46" stroke="#ffffff" stroke-width="1" stroke-dasharray="1 1"/>
        <line x1="39" y1="50" x2="47" y2="50" stroke="#ffffff" stroke-width="1" stroke-dasharray="1 1"/>
      </svg>`;
    case 'chief-of-staff':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#eef3ec"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#d3e2cf" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M28 32 Q32 34 36 32" stroke="#283d36" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#9bac80" stroke="#283d36" stroke-width="2"/>
        <rect x="38" y="41" width="14" height="15" rx="2" fill="#fdfaf3" stroke="#283d36" stroke-width="1.5"/>
        <circle cx="42" cy="46" r="1.5" fill="#c97858"/>
        <line x1="45" y1="46" x2="49" y2="46" stroke="#283d36" stroke-width="1"/>
        <circle cx="42" cy="50" r="1.5" fill="#699a92"/>
        <line x1="45" y1="50" x2="49" y2="50" stroke="#283d36" stroke-width="1"/>
      </svg>`;
    case 'librarian':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#edf7f5"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#cdeae3" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M29 32 Q32 34 35 32" stroke="#283d36" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#699a92" stroke="#283d36" stroke-width="2"/>
        <path d="M38 43 L49 41 L49 54 L38 56 Z" fill="#f7f3e8" stroke="#283d36" stroke-width="1.5"/>
        <path d="M43 42 L43 55" stroke="#283d36" stroke-width="1"/>
      </svg>`;
    case 'interpreter':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#fcf0ee"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#fad5cf" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M29 32 L35 32" stroke="#283d36" stroke-width="1.5" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#d98b7d" stroke="#283d36" stroke-width="2"/>
        <circle cx="44" cy="47" r="6" fill="#ffffff" stroke="#283d36" stroke-width="1.6"/>
        <line x1="48" y1="51" x2="54" y2="57" stroke="#283d36" stroke-width="2.2" stroke-linecap="round"/>
      </svg>`;
    case 'dispatcher':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#fbf2eb"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#f5d8c7" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M28 32 Q32 35 36 32" stroke="#283d36" stroke-width="1.5" fill="none" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#c97858" stroke="#283d36" stroke-width="2"/>
        <rect x="36" y="44" width="15" height="12" rx="2" fill="#fdfaf3" stroke="#283d36" stroke-width="1.5"/>
        <polygon points="36,44 43.5,49 51,44" fill="none" stroke="#283d36" stroke-width="1.2"/>
      </svg>`;
    case 'sentinel':
      return `<svg viewBox="0 0 64 64" width="64" height="64" class="ih-portrait-svg" aria-hidden="true">
        <rect width="64" height="64" rx="16" fill="#ebedf3"/>
        <rect x="18" y="14" width="28" height="24" rx="8" fill="#cbcedc" stroke="#283d36" stroke-width="2"/>
        <circle cx="26" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="26" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="38" cy="24" r="3.5" fill="#ffffff"/>
        <circle cx="38" cy="24" r="1.8" fill="#1e2d27"/>
        <circle cx="22" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <circle cx="42" cy="30" r="2" fill="#f4a896" opacity="0.8"/>
        <path d="M28 33 L36 33" stroke="#283d36" stroke-width="1.5" stroke-linecap="round"/>
        <path d="M14 40 C14 36, 22 36, 32 36 C42 36, 50 36, 50 40 L52 60 L12 60 Z" fill="#283d36" stroke="#16231f" stroke-width="2"/>
        <path d="M40 42 Q46 40 52 42 Q52 48 46 54 Q40 48 40 42 Z" fill="#d5b466" stroke="#ffffff" stroke-width="1.2"/>
        <line x1="46" y1="44" x2="46" y2="51" stroke="#283d36" stroke-width="1"/>
      </svg>`;
  }
}

export function mountHome(host: HTMLElement, callbacks: MountHomeCallbacks): HomeHandle {
  let isVisible = true;
  let isKitOpen = false;
  let selectedSlug: ResidentSlug | null = null;
  let pollTimer: number | null = null;
  let tourTimer: number | null = null;
  let tourIndex = 0;
  let tourActiveSlug: ResidentSlug = RESIDENTS[0].slug;
  let isDemoTourRunning = false;
  let pendingController: AbortController | null = null;
  let requestGeneration = 0;
  let expectedScopeMode: 'public-fixtures' | 'local-private' | null = null;
  let notesOpen = false;

  let projection: ProjectionState = {
    snapshot: null,
    scopeMode: null,
    tenant: null,
    source: 'unavailable',
    stale: false,
    lastUpdatedMs: null,
    label: 'Connecting to crew sources...'
  };

  host.innerHTML = `
    <div class="ih-home-root" id="ih-home-root">
      <header class="ih-mission-strip" id="ih-mission-strip">
        <div class="ih-mission-header-bar">
          <div class="ih-mission-title-group">
            <div class="ih-stamp-tag">ENCOUNTER MAP</div>
            <h1 class="ih-mission-headline">A little town. A real crew.</h1>
          </div>
          <div class="ih-mission-actions">
            <button type="button" class="ih-btn ih-btn-accent" id="ih-btn-meet">Meet crew</button>
            <button type="button" class="ih-btn ih-btn-outline" id="ih-btn-follow">Follow route</button>
            <button type="button" class="ih-btn ih-btn-outline" id="ih-btn-tour">Try crew tour</button>
            <button type="button" class="ih-btn ih-btn-outline" id="ih-btn-blueprint">Open blueprint</button>
            <button type="button" class="ih-btn ih-btn-subtle" id="ih-btn-notes-toggle" aria-expanded="false">Map & source notes</button>
          </div>
        </div>

        <div class="ih-demo-banner" id="ih-demo-banner" hidden>
          <div class="ih-demo-banner-content">
            <span class="ih-demo-pill">DEMO</span>
            <span class="ih-demo-text">Crew tour · local demonstration, not live activity</span>
          </div>
          <button type="button" class="ih-btn ih-btn-subtle ih-btn-sm" id="ih-btn-stop-tour">Stop tour</button>
        </div>

        <details class="ih-connection-details" id="ih-conn-details">
          <summary class="ih-conn-summary">
            <span class="ih-conn-indicator" id="ih-conn-dot"></span>
            <span class="ih-conn-label-text" id="ih-conn-label">Connecting...</span>
          </summary>
          <div class="ih-conn-body">
            <div class="ih-conn-row">
              <span class="ih-conn-k">Scope</span>
              <span class="ih-conn-v" id="ih-conn-scope">unknown</span>
            </div>
            <div class="ih-conn-row">
              <span class="ih-conn-k">Tenant</span>
              <span class="ih-conn-v" id="ih-conn-tenant">none</span>
            </div>
            <div class="ih-conn-row">
              <span class="ih-conn-k">Source</span>
              <span class="ih-conn-v" id="ih-conn-source">none</span>
            </div>
            <div class="ih-conn-row">
              <span class="ih-conn-k">Staleness</span>
              <span class="ih-conn-v" id="ih-conn-stale">fresh</span>
            </div>
            <div class="ih-conn-row ih-conn-row-actions">
              <button type="button" class="ih-btn ih-btn-subtle ih-btn-sm" id="ih-btn-conn-refresh">Refresh source</button>
            </div>
          </div>
        </details>
      </header>

      <div class="ih-dialogue-layer" id="ih-dialogue-layer" hidden>
        <section class="ih-ticket-dialogue" id="ih-ticket-dialogue" role="region" aria-label="Crew member file">
          <div class="ih-ticket-head">
            <div class="ih-ticket-portrait-slot" id="ih-ticket-portrait"></div>
            <div class="ih-ticket-meta">
              <div class="ih-ticket-subrow">
                <span class="ih-ticket-role" id="ih-ticket-role">Role</span>
                <span class="ih-ticket-state-badge" id="ih-ticket-state">active</span>
              </div>
              <h2 class="ih-ticket-name" id="ih-ticket-name">Resident</h2>
            </div>
            <button type="button" class="ih-ticket-close" id="ih-ticket-close" aria-label="Close crew ticket">✕</button>
          </div>

          <div class="ih-ticket-body">
            <p class="ih-ticket-greeting" id="ih-ticket-greeting"></p>
            <div class="ih-ticket-evidence-box">
              <div class="ih-ticket-field">
                <span class="ih-ticket-k">Evidence</span>
                <span class="ih-ticket-v" id="ih-ticket-evidence"></span>
              </div>
              <div class="ih-ticket-field">
                <span class="ih-ticket-k">Reason</span>
                <span class="ih-ticket-v" id="ih-ticket-reason"></span>
              </div>
              <div class="ih-ticket-field" id="ih-ticket-record-wrap">
                <span class="ih-ticket-k">Record</span>
                <span class="ih-ticket-v" id="ih-ticket-record"></span>
              </div>
              <div class="ih-ticket-field" id="ih-ticket-station-wrap">
                <span class="ih-ticket-k">Station</span>
                <span class="ih-ticket-v" id="ih-ticket-station"></span>
              </div>
            </div>

            <div class="ih-ticket-sources-block">
              <span class="ih-ticket-k">Registered sources</span>
              <div class="ih-ticket-sources-list" id="ih-ticket-sources"></div>
            </div>
          </div>

          <div class="ih-ticket-actions">
            <button type="button" class="ih-btn ih-btn-accent" id="ih-ticket-btn-meet">Meet at station</button>
            <button type="button" class="ih-btn ih-btn-outline" id="ih-ticket-btn-agent">Open agent field kit</button>
          </div>
        </section>
      </div>

      <nav class="ih-belt-wrap" aria-label="Crew resident tokens">
        <div class="ih-belt-scroll" id="ih-belt-scroll" role="toolbar" aria-label="Resident selector">
        </div>
      </nav>
    </div>
  `;

  const rootEl = host.querySelector('#ih-home-root') as HTMLElement;
  const beltEl = host.querySelector('#ih-belt-scroll') as HTMLElement;
  const dialogueLayerEl = host.querySelector('#ih-dialogue-layer') as HTMLElement;
  const demoBannerEl = host.querySelector('#ih-demo-banner') as HTMLElement;
  const connLabelEl = host.querySelector('#ih-conn-label') as HTMLElement;
  const connDotEl = host.querySelector('#ih-conn-dot') as HTMLElement;
  const connScopeEl = host.querySelector('#ih-conn-scope') as HTMLElement;
  const connTenantEl = host.querySelector('#ih-conn-tenant') as HTMLElement;
  const connSourceEl = host.querySelector('#ih-conn-source') as HTMLElement;
  const connStaleEl = host.querySelector('#ih-conn-stale') as HTMLElement;
  const btnNotesToggle = host.querySelector('#ih-btn-notes-toggle') as HTMLButtonElement;

  function getActivePresenceList(): ResidentPresence[] {
    if (isDemoTourRunning) {
      const activeSlug = tourActiveSlug;
      return demoPresence(activeSlug);
    }
    return derivePresence(projection.snapshot, Date.now(), projection.stale);
  }

  function renderBelt(): void {
    const presences = getActivePresenceList();
    const presenceMap = new Map(presences.map((p) => [p.slug, p]));

    const focusedId = host.contains(document.activeElement) ? (document.activeElement as HTMLElement).id : '';
    beltEl.innerHTML = '';
    for (const res of RESIDENTS) {
      const pres = presenceMap.get(res.slug);
      const state = pres ? pres.state : 'unknown';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `ih-token-btn ${selectedSlug === res.slug ? 'ih-token-selected' : ''}`;
      btn.id = `ih-token-${res.slug}`;
      btn.setAttribute('aria-pressed', selectedSlug === res.slug ? 'true' : 'false');
      btn.setAttribute('aria-label', `${res.name}, ${res.role}, state: ${pres ? pres.label : 'Unknown'}`);
      btn.style.setProperty('--ih-token-color', res.color);
      btn.style.setProperty('--ih-token-accent', res.accent);

      btn.innerHTML = `
        <div class="ih-token-portrait">${getFixedPortraitSvg(res.slug)}</div>
        <div class="ih-token-meta">
          <span class="ih-token-name"></span>
          <span class="ih-token-role"></span>
          <span class="ih-token-state-tag ih-token-state-${state}"></span>
        </div>
      `;
      const shortRole: Record<ResidentSlug, string> = {ceo:'CEO', cto:'CTO', 'chief-of-staff':'Routing', librarian:'Knowledge', interpreter:'Interpretation', dispatcher:'Dispatch', sentinel:'Audit'};
      (btn.querySelector('.ih-token-name') as HTMLElement).textContent = shortRole[res.slug];
      (btn.querySelector('.ih-token-role') as HTMLElement).textContent = res.station;
      (btn.querySelector('.ih-token-state-tag') as HTMLElement).textContent = pres ? pres.label : 'Unknown';

      btn.addEventListener('click', () => {
        if (selectedSlug === res.slug) {
          closeDialogue();
        } else {
          openDialogue(res.slug);
        }
      });

      beltEl.appendChild(btn);
    }
    if (focusedId.startsWith('ih-token-')) document.getElementById(focusedId)?.focus();
  }

  function updateConnectionUI(): void {
    connLabelEl.textContent = projection.label;
    connScopeEl.textContent = projection.scopeMode || 'none';
    connTenantEl.textContent = projection.tenant || 'none';
    connSourceEl.textContent = projection.source;
    connStaleEl.textContent = projection.stale ? 'Stale' : 'Fresh snapshot';

    connDotEl.className = 'ih-conn-indicator ' + (
      projection.source === 'unavailable' ? 'ih-conn-err' :
      projection.stale ? 'ih-conn-stale' : 'ih-conn-ok'
    );
  }

  function openDialogue(slug: ResidentSlug): void {
    const activeControl = host.contains(document.activeElement) ? (document.activeElement as HTMLElement).id : '';
    selectedSlug = slug;
    const res = RESIDENTS.find((r) => r.slug === slug);
    if (!res) return;
    const presences = getActivePresenceList();
    const pres = presences.find((p) => p.slug === slug);

    const portraitSlot = host.querySelector('#ih-ticket-portrait') as HTMLElement;
    const roleEl = host.querySelector('#ih-ticket-role') as HTMLElement;
    const stateEl = host.querySelector('#ih-ticket-state') as HTMLElement;
    const nameEl = host.querySelector('#ih-ticket-name') as HTMLElement;
    const greetingEl = host.querySelector('#ih-ticket-greeting') as HTMLElement;
    const evidenceEl = host.querySelector('#ih-ticket-evidence') as HTMLElement;
    const reasonEl = host.querySelector('#ih-ticket-reason') as HTMLElement;
    const recordEl = host.querySelector('#ih-ticket-record') as HTMLElement;
    const recordWrap = host.querySelector('#ih-ticket-record-wrap') as HTMLElement;
    const stationEl = host.querySelector('#ih-ticket-station') as HTMLElement;
    const sourcesList = host.querySelector('#ih-ticket-sources') as HTMLElement;
    const btnMeet = host.querySelector('#ih-ticket-btn-meet') as HTMLButtonElement;
    const btnAgent = host.querySelector('#ih-ticket-btn-agent') as HTMLButtonElement;

    portraitSlot.innerHTML = getFixedPortraitSvg(res.slug);
    roleEl.textContent = res.role;
    nameEl.textContent = res.name;
    greetingEl.textContent = `“${res.greeting}”`;
    stationEl.textContent = `${res.station} (${res.nodeId})`;

    if (pres) {
      stateEl.textContent = pres.label;
      stateEl.className = `ih-ticket-state-badge ih-state-${pres.state}`;
      evidenceEl.textContent = `${pres.evidence}`;
      reasonEl.textContent = pres.reason;
      if (pres.recordId || pres.observedAt) {
        recordWrap.hidden = false;
        recordEl.textContent = `${pres.recordId || 'No-ID'} ${pres.observedAt ? '· ' + pres.observedAt : ''}`;
      } else {
        recordWrap.hidden = true;
      }
    } else {
      stateEl.textContent = 'No active evidence';
      stateEl.className = 'ih-ticket-state-badge ih-state-unknown';
      evidenceEl.textContent = 'unobserved';
      reasonEl.textContent = 'No evidence observed in active projection.';
      recordWrap.hidden = true;
    }

    sourcesList.innerHTML = '';
    for (const src of res.sources) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'ih-source-chip';
      b.textContent = src;
      b.id = `ih-source-${res.slug}-${res.sources.indexOf(src)}`;
      b.addEventListener('click', () => {
        callbacks.openDocument(src);
      });
      sourcesList.appendChild(b);
    }

    btnMeet.onclick = () => {
      closeDialogue();
      callbacks.focusNode(res.nodeId);
    };
    btnAgent.onclick = () => {
      callbacks.openAgent(res.nodeId);
    };

    dialogueLayerEl.hidden = false;
    renderBelt();
    if (activeControl) document.getElementById(activeControl)?.focus();
  }

  function closeDialogue(): void {
    const previous = selectedSlug;
    selectedSlug = null;
    dialogueLayerEl.hidden = true;
    renderBelt();
    if (previous) {
      const btn = host.querySelector(`#ih-token-${previous}`) as HTMLButtonElement | null;
      btn?.focus();
    }
  }

  function broadcastPresence(): void {
    const pres = getActivePresenceList();
    callbacks.onPresence(pres);
    renderBelt();
    if (selectedSlug) {
      openDialogue(selectedSlug);
    }
  }

  function applyProjection(next: Partial<ProjectionState>): void {
    if (next.scopeMode) {
      expectedScopeMode = next.scopeMode;
    }
    projection = { ...projection, ...next };
    if (next.snapshot === null && expectedScopeMode === 'local-private') {
      if (selectedSlug) closeDialogue();
      for (const id of ['ih-ticket-reason', 'ih-ticket-record', 'ih-ticket-evidence']) { const field = host.querySelector('#' + id); if (field) field.textContent = ''; }
    }
    updateConnectionUI();
    broadcastPresence();
  }

  function startDemoTour(): void {
    isDemoTourRunning = true;
    tourIndex = 0;
    demoBannerEl.hidden = false;
    const step = () => {
      if (!isDemoTourRunning) return;
      tourActiveSlug = RESIDENTS[tourIndex % RESIDENTS.length].slug;
      const currentResident = RESIDENTS[tourIndex % RESIDENTS.length];
      broadcastPresence();
      callbacks.focusNode(currentResident.nodeId);
      tourIndex++;
      tourTimer = window.setTimeout(step, 8000);
    };
    step();
  }

  function stopDemoTour(): void {
    if (!isDemoTourRunning) return;
    isDemoTourRunning = false;
    if (tourTimer) {
      clearTimeout(tourTimer);
      tourTimer = null;
    }
    demoBannerEl.hidden = true;
    broadcastPresence();
  }

  async function fetchCockpitFixture(gen: number, signal: AbortSignal): Promise<void> {
    try {
      const res = await fetch('/cockpit-fixture.json', { signal });
      if (!res.ok) throw new Error(`Fixture fetch failed: ${res.status}`);
      const json = await res.json();
      const validated = validateSnapshot(json);
      if (validated.scope.mode !== 'public-fixtures') throw new Error('Public fixture scope required');
      if (gen !== requestGeneration || signal.aborted) return;
      applyProjection({
        snapshot: validated,
        scopeMode: 'public-fixtures',
        tenant: null,
        source: 'fixture',
        stale: true,
        lastUpdatedMs: Date.now(),
        label: 'Disconnected · public source fixture · stale'
      });
    } catch (err: unknown) {
      if (gen !== requestGeneration) return;
      applyProjection({
        snapshot: null,
        scopeMode: 'public-fixtures',
        tenant: null,
        source: 'unavailable',
        stale: true,
        lastUpdatedMs: Date.now(),
        label: 'Unavailable · public fixture load failed'
      });
    }
  }

  async function requestSnapshotPoll(): Promise<void> {
    if (!isVisible || isKitOpen || document.hidden) return;
    if (pendingController) return;

    const gen = ++requestGeneration;
    const controller = new AbortController();
    pendingController = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), 8000);

    try {
      const requestedTenant = projection.tenant;
      const requestedMode = expectedScopeMode;
      const snap = await loadSnapshot(requestedTenant || undefined, {signal: controller.signal, timeoutMs: 8000});
      if (requestedMode && snap.scope.mode !== requestedMode) throw new Error('Snapshot mode changed');
      if (requestedTenant && snap.scope.tenant !== requestedTenant) throw new Error('Snapshot tenant changed');
      clearTimeout(timeoutId);
      if (gen !== requestGeneration || controller.signal.aborted) return;
      pendingController = null;

      applyProjection({
        snapshot: snap,
        scopeMode: snap.scope.mode,
        tenant: snap.scope.tenant,
        source: 'api',
        stale: false,
        lastUpdatedMs: Date.now(),
        label: 'Connected · source projection'
      });
    } catch (err: unknown) {
      clearTimeout(timeoutId);
      if (gen !== requestGeneration) return;
      pendingController = null;

      if (expectedScopeMode === 'local-private' || projection.tenant) {
        applyProjection({
          snapshot: null,
          scopeMode: 'local-private',
          tenant: projection.tenant,
          source: 'unavailable',
          stale: true,
          lastUpdatedMs: Date.now(),
          label: 'Unavailable · selected source scope offline'
        });
        if (selectedSlug) {
          closeDialogue();
        }
      } else {
        if (!projection.snapshot) {
          const fixtureCtrl = new AbortController();
          const fixtureTimeout = window.setTimeout(() => fixtureCtrl.abort(), 8000);
          pendingController = fixtureCtrl;
          await fetchCockpitFixture(gen, fixtureCtrl.signal);
          clearTimeout(fixtureTimeout);
          if (pendingController === fixtureCtrl) pendingController = null;
        } else {
          applyProjection({
            stale: true,
            source: 'unavailable',
            label: 'Connection lost · retaining stale projection'
          });
        }
      }
    }
  }

  function setupPolling(): void {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = window.setInterval(() => {
      if (isVisible && !isKitOpen && !document.hidden && !pendingController) {
        requestSnapshotPoll();
      }
    }, 15000);
  }

  const handleVisibilityChange = (): void => {
    if (document.hidden) {
      if (isDemoTourRunning) stopDemoTour();
    } else {
      if (isVisible && !isKitOpen) {
        requestSnapshotPoll();
      }
    }
  };

  const handleSnapshotEvent = (e: Event): void => {
    const customEvent = e as CustomEvent<{
      snapshot: OpsSnapshot | null;
      scopeMode: 'public-fixtures' | 'local-private' | null;
      tenant: string | null;
      source: 'api' | 'fixture' | 'unavailable';
      stale: boolean;
    }>;
    if (!customEvent.detail) return;

    if (pendingController) {
      pendingController.abort();
      pendingController = null;
    }
    requestGeneration++;

    const detail = customEvent.detail;
    if (detail.scopeMode) {
      expectedScopeMode = detail.scopeMode;
    }

    if (detail.snapshot === null && expectedScopeMode === 'local-private') {
      applyProjection({
        snapshot: null,
        scopeMode: 'local-private',
        tenant: detail.tenant || null,
        source: detail.source || 'unavailable',
        stale: detail.stale ?? true,
        lastUpdatedMs: Date.now(),
        label: 'Cleared · private ops disconnected'
      });
      if (selectedSlug) closeDialogue();
      return;
    }

    let validatedSnap: OpsSnapshot | null = null;
    if (detail.snapshot) {
      try {
        validatedSnap = validateSnapshot(detail.snapshot);
        if (detail.scopeMode && validatedSnap.scope.mode !== detail.scopeMode) throw new Error('Bridge mode mismatch');
        if (validatedSnap.scope.tenant !== detail.tenant) throw new Error('Bridge tenant mismatch');
      } catch {
        validatedSnap = null;
      }
    }

    applyProjection({
      snapshot: validatedSnap,
      scopeMode: detail.scopeMode || expectedScopeMode,
      tenant: detail.tenant || null,
      source: detail.snapshot && !validatedSnap ? 'unavailable' : detail.source || 'api',
      stale: detail.snapshot && !validatedSnap ? true : detail.stale ?? false,
      lastUpdatedMs: Date.now(),
      label: detail.snapshot && !validatedSnap ? 'Unavailable · scope projection rejected' : detail.stale ? 'Field Kit · stale source projection' : 'Field Kit · current source projection'
    });
  };

  const handleKeyDown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape' && selectedSlug && !isKitOpen && !document.querySelector('dialog[open]')) {
      if (rootEl.contains(document.activeElement)) {
        e.stopPropagation();
        closeDialogue();
      }
    }
  };

  host.querySelector('#ih-btn-meet')?.addEventListener('click', () => openDialogue(RESIDENTS[0].slug));
  host.querySelector('#ih-btn-follow')?.addEventListener('click', () => callbacks.followTour());
  host.querySelector('#ih-btn-tour')?.addEventListener('click', () => {
    if (isDemoTourRunning) {
      stopDemoTour();
    } else {
      startDemoTour();
    }
  });
  host.querySelector('#ih-btn-stop-tour')?.addEventListener('click', () => {
    stopDemoTour();
  });
  host.querySelector('#ih-btn-blueprint')?.addEventListener('click', () => {
    callbacks.openBlueprint();
  });
  btnNotesToggle?.addEventListener('click', () => {
    notesOpen = !notesOpen;
    btnNotesToggle.setAttribute('aria-expanded', notesOpen ? 'true' : 'false');
    document.body.classList.toggle('source-notes-open', notesOpen);
    callbacks.toggleNotes(notesOpen);
  });
  host.querySelector('#ih-btn-conn-refresh')?.addEventListener('click', () => {
    requestSnapshotPoll();
  });
  host.querySelector('#ih-ticket-close')?.addEventListener('click', () => {
    closeDialogue();
  });

  document.addEventListener('visibilitychange', handleVisibilityChange);
  document.addEventListener('cockpit-snapshot', handleSnapshotEvent as EventListener);
  window.addEventListener('keydown', handleKeyDown);

  document.body.classList.add('home-explore');
  renderBelt();
  updateConnectionUI();
  setupPolling();
  requestSnapshotPoll();

  return {
    setVisible(visible: boolean): void {
      isVisible = visible;
      host.hidden = !visible || isKitOpen;
      if (!visible) {
        if (isDemoTourRunning) stopDemoTour();
        if (pendingController) {
          requestGeneration++;
          pendingController.abort();
          pendingController = null;
        }
      } else {
        if (!isKitOpen) {
          requestSnapshotPoll();
        }
      }
    },

    setKitOpen(open: boolean): void {
      isKitOpen = open;
      host.hidden = open || !isVisible;
      document.body.classList.toggle('field-kit-open', open);
      if (open) {
        if (isDemoTourRunning) stopDemoTour();
        if (pendingController) {
          requestGeneration++;
          pendingController.abort();
          pendingController = null;
        }
      } else if (isVisible) {
        requestSnapshotPoll();
      }
    },

    selectResident(slug: string): void {
      const found = RESIDENTS.find((r) => r.slug === slug);
      if (found) {
        openDialogue(found.slug);
      }
    },

    dispose(): void {
      if (pollTimer) clearInterval(pollTimer);
      if (tourTimer) clearTimeout(tourTimer);
      if (pendingController) pendingController.abort();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      document.removeEventListener('cockpit-snapshot', handleSnapshotEvent as EventListener);
      window.removeEventListener('keydown', handleKeyDown);
      document.body.classList.remove('home-explore');
      document.body.classList.remove('field-kit-open');
      document.body.classList.remove('source-notes-open');
      host.innerHTML = '';
    }
  };
}
