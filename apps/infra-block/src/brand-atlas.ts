import * as THREE from 'three';
import type { BrandKnowledge, BrandPlanning } from './brand-summary.js';
import { summarizeAsks, type TenantAsk } from './tenant-asks';

export interface BrandTenant {
  slug: string;
  name: string;
  availability: 'fixture' | 'local';
  knowledge?: BrandKnowledge;
  planning?: BrandPlanning;
}

export type BrandAtlasUpdate = (
  tenants: BrandTenant[] | null,
  mode: string,
  stale: boolean,
) => void;

export interface BrandAtlasHandle {
  update: BrandAtlasUpdate;
  dispose: () => void;
}

export interface BrandMarkersHandle {
  group: THREE.Group;
  update: BrandAtlasUpdate;
  setAskCounts: (counts: Record<string, number>) => void;
  pick: (raycaster: THREE.Raycaster, maxDistance?: number) => boolean;
  dispose: () => void;
}

const MAX_TENANTS = 32;
const MARKER_RADIUS = 0.5;
const RING_HEIGHT = 0.7;
const ARC_RADIUS = 3.6;
const LOCAL_GOLD = 0xc8a951;
const FIXTURE_BLUE = 0x2f6fed;

function fail(message: string): never {
  throw new Error(message);
}

function assertTenants(tenants: BrandTenant[] | null): BrandTenant[] {
  if (tenants === null) return [];
  if (!Array.isArray(tenants)) fail('Invalid tenants: expected array');
  if (tenants.length > MAX_TENANTS) fail(`Invalid tenants: maximum ${MAX_TENANTS}`);
  for (const tenant of tenants) {
    if (typeof tenant.slug !== 'string' || tenant.slug.length === 0 || tenant.slug.length > 128) {
      fail('Invalid tenant.slug');
    }
    if (typeof tenant.name !== 'string' || tenant.name.length > 128) {
      fail('Invalid tenant.name');
    }
    if (tenant.availability !== 'fixture' && tenant.availability !== 'local') {
      fail('Invalid tenant.availability');
    }
  }
  return tenants;
}

function clearElement(host: HTMLElement): void {
  while (host.firstChild) host.removeChild(host.firstChild);
}

function scopeLabel(availability: BrandTenant['availability']): string {
  return availability === 'local' ? 'local private data' : 'public fixtures';
}

function askCountSprite(count: number): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (context) {
    context.clearRect(0, 0, 128, 128);
    context.beginPath();
    context.arc(64, 64, 52, 0, Math.PI * 2);
    context.fillStyle = '#9a3b2f';
    context.fill();
    context.fillStyle = '#f4edda';
    context.font = '700 64px sans-serif';
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillText(String(count), 64, 66);
  }
  const material = new THREE.SpriteMaterial({map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false});
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(0.85, 0.85, 1);
  return sprite;
}

function releaseSprite(sprite: THREE.Sprite): void {
  const material = sprite.material;
  if (!Array.isArray(material)) {
    material.map?.dispose();
    material.dispose();
  }
}

export function mountBrandAtlas(
  host: HTMLElement,
  onSelect: (slug: string) => void,
  onVisit: () => void = () => {},
): BrandAtlasHandle {
  const root = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Brand atlas';
  root.className = 'sg-brand-atlas';
  root.appendChild(summary);

  const list = document.createElement('div');
  root.appendChild(list);
  host.appendChild(root);

  const clickHandlers: Array<{ button: HTMLButtonElement; handler: () => void }> = [];
  let askCounts: Record<string, number> = {};
  let shown: {tenants: BrandTenant[] | null; mode: string; stale: boolean} | null = null;

  const update: BrandAtlasUpdate = (tenants, mode, stale) => {
    shown = {tenants, mode, stale};
    for (const entry of clickHandlers) {
      entry.button.removeEventListener('click', entry.handler);
    }
    clickHandlers.length = 0;
    clearElement(list);

    if (stale || tenants === null) { const warning = document.createElement('p'); warning.textContent = 'Brand evidence unavailable · reconnect the Field Kit'; list.appendChild(warning); return; }

    const bounded = assertTenants(tenants);
    const modeLine = document.createElement('p');
    modeLine.textContent = `Mode: ${mode}`;
    list.appendChild(modeLine);

    const visit = document.createElement('button'); visit.type = 'button'; visit.textContent = 'Visit brand station';
    visit.onclick = () => { root.open = false; onVisit(); }; list.appendChild(visit);
    for (const tenant of bounded) {
      const row = document.createElement('div');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = tenant.slug;
      button.setAttribute('aria-label', `${tenant.slug} brand`);

      const scope = document.createElement('span');
      scope.textContent = scopeLabel(tenant.availability);

      const handler = () => { root.open = false; onSelect(tenant.slug); };
      button.addEventListener('click', handler);
      clickHandlers.push({ button, handler });

      row.appendChild(button);
      row.appendChild(scope);
      const waiting = askCounts[tenant.slug] ?? 0;
      if (waiting > 0) {
        const count = document.createElement('span');
        count.className = 'sg-brand-ask-count';
        count.textContent = String(waiting);
        row.appendChild(count);
      }
      list.appendChild(row);
    }
  };

  const onAsks = (event: Event): void => {
    const detail = (event as CustomEvent<TenantAsk[] | null>).detail;
    askCounts = Array.isArray(detail) ? summarizeAsks(detail).byTenant : {};
    if (shown) update(shown.tenants, shown.mode, shown.stale);
  };
  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('tenant-asks', onAsks);
  }

  const dispose = (): void => {
    if (typeof document !== 'undefined' && typeof document.removeEventListener === 'function') {
      document.removeEventListener('tenant-asks', onAsks);
    }
    for (const entry of clickHandlers) {
      entry.button.removeEventListener('click', entry.handler);
    }
    clickHandlers.length = 0;
    clearElement(host);
  };

  return { update, dispose };
}

export function createBrandMarkers(
  anchor: THREE.Vector3,
  onSelect: (slug: string) => void,
): BrandMarkersHandle {
  const sphereGeometry = new THREE.SphereGeometry(MARKER_RADIUS, 16, 16);
  const localMaterial = new THREE.MeshBasicMaterial({ color: LOCAL_GOLD });
  const fixtureMaterial = new THREE.MeshBasicMaterial({ color: FIXTURE_BLUE });

  const group = new THREE.Group();
  group.position.copy(anchor);

  const meshes: THREE.Mesh[] = [];
  let disposed = false;
  let askCounts: Record<string, number> = {};

  const clearSprites = (): void => {
    for (const child of [...group.children]) {
      if (!(child as THREE.Sprite).isSprite) continue;
      group.remove(child);
      releaseSprite(child as THREE.Sprite);
    }
  };

  const clearMeshes = (): void => {
    for (const mesh of meshes) {
      group.remove(mesh);
    }
    meshes.length = 0;
  };

  const paintAskCounts = (): void => {
    clearSprites();
    if (disposed) return;
    for (const mesh of meshes) {
      const slug = mesh.userData.slug;
      const count = typeof slug === 'string' ? askCounts[slug] : undefined;
      if (!count) continue;
      const sprite = askCountSprite(count);
      sprite.position.copy(mesh.position);
      sprite.position.y += MARKER_RADIUS + 0.55;
      sprite.userData.slug = slug;
      group.add(sprite);
    }
  };

  const setAskCounts = (counts: Record<string, number>): void => {
    const next: Record<string, number> = {};
    for (const [slug, count] of Object.entries(counts)) {
      if (Number.isInteger(count) && count > 0) next[slug] = count;
    }
    askCounts = next;
    paintAskCounts();
  };

  const update: BrandAtlasUpdate = (tenants, _mode, stale) => {
    clearMeshes();
    clearSprites();
    if (disposed) return;
    if (stale || tenants === null) return;
    const bounded = assertTenants(tenants);

    const count = bounded.length;
    for (let i = 0; i < count; i += 1) {
      const tenant = bounded[i];
      const material = tenant.availability === 'local' ? localMaterial : fixtureMaterial;
      const mesh = new THREE.Mesh(sphereGeometry, material);
      const angle = count <= 1 ? 0 : (i / count) * Math.PI * 2;
      mesh.position.set(Math.cos(angle) * ARC_RADIUS, RING_HEIGHT, Math.sin(angle) * ARC_RADIUS);
      mesh.userData.slug = tenant.slug;
      group.add(mesh);
      meshes.push(mesh);
    }
    paintAskCounts();
  };

  const pick = (raycaster: THREE.Raycaster, maxDistance = Infinity): boolean => {
    if (!group.visible || meshes.length === 0) return false;
    group.updateMatrixWorld(true);
    const hits = raycaster.intersectObjects(meshes, false);
    if (hits.length === 0) return false;
    let nearest = hits[0];
    for (let i = 1; i < hits.length; i += 1) {
      if (hits[i].distance < nearest.distance) nearest = hits[i];
    }
    if (nearest.distance >= maxDistance) return false;
    const slug = nearest.object.userData.slug;
    if (typeof slug !== 'string' || slug.length === 0) fail('Invalid marker slug');
    onSelect(slug);
    return true;
  };

  const dispose = (): void => {
    if (disposed) return;
    disposed = true;
    clearSprites();
    clearMeshes();
    sphereGeometry.dispose();
    localMaterial.dispose();
    fixtureMaterial.dispose();
    if (group.parent) group.parent.remove(group);
  };

  return { group, update, setAskCounts, pick, dispose };
}
