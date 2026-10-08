import './fleet-atlas.css';
import { FLEET_LAYOUT, fleetActivity, fleetNodes, type FleetProjection } from './fleet-model';
import { derivePresence } from './residents';

type WorldView = 'town' | 'archipelago';

export interface FleetAtlasHandle {
  setProjection(projection: FleetProjection): void;
  setSelection(id: string, view: WorldView): void;
  setVisible(visible: boolean): void;
  dispose(): void;
}

/** The atlas only changes the local view; fleet data remains a read-only projection. */
export function mountFleetAtlas(
  host: HTMLElement,
  callbacks: { visitIsland(id: string): void; setWorldView(view: WorldView): void }
): FleetAtlasHandle {
  let disposed = false;
  let selectedId = 'mac-coding-1';
  let view: WorldView = 'town';
  let projection: FleetProjection = { snapshot: null, scopeMode: null, tenant: null, stale: true, source: 'unavailable' };

  const root = document.createElement('section');
  root.className = 'sg-fleet-atlas';
  root.id = 'sg-fleet-atlas';
  root.setAttribute('aria-label', 'Fleet island atlas');
  root.dataset.view = view;

  const heading = document.createElement('div');
  heading.className = 'sg-fleet-heading';
  const title = document.createElement('div');
  title.className = 'sg-fleet-title';
  const titleText = document.createElement('strong');
  titleText.textContent = 'Fleet archipelago';
  const sourceText = document.createElement('span');
  sourceText.className = 'sg-fleet-source';
  const worldNote = document.createElement('span');
  worldNote.className = 'sg-fleet-world-note';
  worldNote.textContent = 'Brands: shared portfolio · Other land: unmapped scenery';
  worldNote.title = 'Brand stations and planning artifacts are global portfolio sources, without a device assignment. Decorative islets beyond the four fleet slots are unmapped scenery.';
  title.append(titleText, sourceText, worldNote);
  const actions = document.createElement('div');
  actions.className = 'sg-fleet-actions';
  const chart = document.createElement('button');
  chart.type = 'button';
  chart.className = 'sg-fleet-action';
  chart.textContent = 'Chart';
  chart.setAttribute('aria-label', 'Open fleet archipelago chart');
  chart.title = 'Frame all four islands. WASD / arrows explore the horizon.';
  chart.onclick = () => callbacks.setWorldView('archipelago');
  const town = document.createElement('button');
  town.type = 'button';
  town.className = 'sg-fleet-action';
  town.textContent = 'Enter town';
  town.title = 'Return to the selected island town';
  town.onclick = () => callbacks.visitIsland(selectedId);
  actions.append(chart, town);
  heading.append(title, actions);

  const islands = document.createElement('div');
  islands.className = 'sg-fleet-islands';
  const chips = new Map<string, { button: HTMLButtonElement; assignment: HTMLElement; work: HTMLElement }>();
  for (const layout of FLEET_LAYOUT) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'sg-fleet-island';
    button.dataset.island = layout.id;
    const color = layout.color;
    button.style.setProperty('--island-accent', color);
    const thumbnail = document.createElement('span');
    thumbnail.className = 'sg-fleet-thumbnail';
    // A little shoreline, a station, and a flag echo the actual world geometry.
    thumbnail.innerHTML = `<svg viewBox="0 0 52 42" aria-hidden="true"><path class="sg-fleet-water" d="M2 32q8-4 16 0t16 0t16 0M5 38q9-4 17 0t24-1"/><path class="sg-fleet-shore" d="m5 22 9-10 17-2 11 8 4 9-12 5-21-1-8-5Z"/><path class="sg-fleet-land" d="m5 20 9-10 17-2 11 8 4 9-12 5-21-1-8-5Z"/><path class="sg-fleet-building" d="M16 13h16v12H16Z"/><path class="sg-fleet-roof" d="m14 13 10-6 10 6Z"/><path class="sg-fleet-window" d="M19 17h4v4h-4Zm7 0h4v4h-4Z"/><path class="sg-fleet-flag" d="M37 10v14m0-14 8 3-8 3"/></svg>`;
    const caption = document.createElement('span');
    caption.className = 'sg-fleet-caption';
    const name = document.createElement('strong');
    name.textContent = layout.name;
    const assignment = document.createElement('span');
    assignment.className = 'sg-fleet-assignment';
    const work = document.createElement('span');
    work.className = 'sg-fleet-work';
    caption.append(name, assignment, work);
    button.append(thumbnail, caption);
    button.onclick = () => callbacks.visitIsland(layout.id);
    chips.set(layout.id, { button, assignment, work });
    islands.appendChild(button);
  }

  const announcement = document.createElement('span');
  announcement.className = 'sg-fleet-announcement';
  announcement.setAttribute('aria-live', 'polite');
  root.append(heading, islands, announcement);
  host.appendChild(root);
  const layoutObserver = new ResizeObserver(() => {
    if (!disposed && !root.hidden) document.documentElement.style.setProperty('--sg-fleet-height', `${Math.ceil(root.getBoundingClientRect().height)}px`);
  });
  layoutObserver.observe(root);

  function render(): void {
    if (disposed) return;
    const now = Date.now();
    const generated = Date.parse(projection.snapshot?.generatedAt || '');
    const age = now - generated;
    const stale = projection.stale || projection.source === 'unavailable' || !Number.isFinite(age) || age < 0 || age > 120000;
    const snapshot = projection.source === 'unavailable' ? null : projection.snapshot;
    const nodes = fleetNodes(snapshot);
    sourceText.textContent = !snapshot ? 'Source unavailable · Work unknown' :
      stale ? 'Stale source · Work unknown' :
      projection.scopeMode === 'local-private' ? 'Private inventory · Local travel' : 'Public templates · Local travel';
    sourceText.title = snapshot ? `Source snapshot: ${snapshot.generatedAt}. Inventory assignment does not verify device execution.` : 'Connect a source to inspect fleet assignments. Island travel is local exploration.';
    root.dataset.stale = String(stale);
    root.dataset.island = selectedId;
    root.dataset.view = view;
    chart.setAttribute('aria-pressed', String(view === 'archipelago'));
    town.setAttribute('aria-label', `Enter ${FLEET_LAYOUT.find(node => node.id === selectedId)?.name || 'selected island'} town`);

    for (const node of nodes) {
      const chip = chips.get(node.id);
      if (!chip) continue;
      const scoped = snapshot ? { ...snapshot, activity: fleetActivity(snapshot, node.id) } : null;
      const presences = derivePresence(scoped, now, stale || node.assignment === 'planned');
      const observed = presences.filter(presence => presence.evidence === 'observed');
      const active = observed.filter(presence => presence.state === 'active').length;
      const assignment = node.assignment === 'configured' ? 'Configured' : node.assignment === 'template' ? 'Template' : 'Planned';
      const work = observed.length ? 'Work observed' : 'Work unknown';
      chip.assignment.textContent = assignment;
      chip.work.textContent = work;
      chip.button.dataset.assignment = node.assignment;
      chip.button.dataset.work = observed.length ? 'observed' : 'unknown';
      chip.button.setAttribute('aria-pressed', String(node.id === selectedId));
      chip.button.setAttribute('aria-label', `${node.name}, ${assignment}, ${work}. Visit island town.`);
      chip.button.title = `${node.name} · ${assignment}. ${observed.length ? `${active} active crew; ${observed.length} crew with scoped evidence.` : 'No current device-bound crew work evidence.'} ${node.assignment === 'planned' ? 'Device registration pending.' : 'Assignment comes from source inventory; device acceptance is separate.'}`;
    }
  }

  render();
  return {
    setProjection(next): void { projection = next; render(); },
    setSelection(id, nextView): void {
      if (disposed || !FLEET_LAYOUT.some(node => node.id === id)) return;
      const changed = id !== selectedId || nextView !== view;
      selectedId = id;
      view = nextView;
      if (changed) announcement.textContent = `${FLEET_LAYOUT.find(node => node.id === id)?.name}, ${view === 'town' ? 'town view' : 'fleet chart'}. Local exploration.`;
      render();
    },
    setVisible(visible): void { if (!disposed) root.hidden = !visible; },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      layoutObserver.disconnect();
      for (const chip of chips.values()) chip.button.onclick = null;
      chips.clear();
      chart.onclick = null;
      town.onclick = null;
      root.remove();
    }
  };
}
