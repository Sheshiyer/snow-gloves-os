import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { createPrng, createPerlinLike2D, getTerrainSurfaceHeight } from './environment';

/** Coordinates describe the chart, never a machine's physical location. */
export interface IslandSlot { id: string; name: string; wing: string; x: number; z: number; color: string }
export interface ScenerySpec { x: number; z: number; radius: number; seed: string }
export const SEA_LEVEL = -1.6;
export const CHUNK_SIZE = 520;
export const MAX_SCENERY_CHUNKS = 9;

/** Fit actual three-dimensional coast bounds into the visible HUD-free rectangle. */
export function fitCameraDistance(
  camera: THREE.PerspectiveCamera, bounds: THREE.Box3, direction: THREE.Vector3,
  target: THREE.Vector3, minDistance: number, limits: { top: number; bottom: number; horizontal: number }
): number {
  const probe = camera.clone(), normalized = direction.clone().normalize();
  let distance = minDistance;
  for (let attempt = 0; attempt < 100; attempt++) {
    probe.position.copy(target).addScaledVector(normalized, distance);
    probe.lookAt(target); probe.updateMatrixWorld(true);
    let fits = true;
    for (const x of [bounds.min.x, bounds.max.x]) for (const y of [bounds.min.y, bounds.max.y]) for (const z of [bounds.min.z, bounds.max.z]) {
      const projected = new THREE.Vector3(x, y, z).project(probe);
      if (Math.abs(projected.x) > limits.horizontal || projected.y > limits.top || projected.y < limits.bottom || projected.z > 1) fits = false;
    }
    if (fits) return distance;
    distance *= 1.04;
  }
  return distance;
}

export function sceneryForChunk(seed: string, cx: number, cz: number, slots: readonly IslandSlot[]): ScenerySpec[] {
  const rng = createPrng(`${seed}:sea:${cx}:${cz}`);
  const result: ScenerySpec[] = [];
  for (let i = 0; i < 2; i++) {
    const x = (cx + 0.15 + rng() * 0.7) * CHUNK_SIZE;
    const z = (cz + 0.15 + rng() * 0.7) * CHUNK_SIZE;
    const radius = 10 + rng() * 20;
    if (slots.some(slot => Math.hypot(slot.x - x, slot.z - z) < 150 + radius)) continue;
    result.push({ x, z, radius, seed: `${seed}:${cx}:${cz}:${i}` });
  }
  return result;
}

export function chunkKeysAround(x: number, z: number): string[] {
  const cx = Math.floor(x / CHUNK_SIZE), cz = Math.floor(z / CHUNK_SIZE);
  return Array.from({ length: 9 }, (_, index) => `${cx + index % 3 - 1}:${cz + Math.floor(index / 3) - 1}`);
}

/** Rounded headland with an irregular edge and real cliff faces, not a cylinder. */
export function createIslandGeometry(seed: string, radius: number): THREE.BufferGeometry {
  const rng = createPrng(seed);
  const phase = rng() * Math.PI * 2;
  const segments = 32;
  const positions: number[] = [0, 1, 0], colors: number[] = [];
  const indices: number[] = [];
  const palette = ['#a4b593', '#a4b593', '#a3aa86', '#b6ad95', '#817e6a', '#6b908c'].map(c => new THREE.Color(c));
  const centerColor = palette[0];
  colors.push(centerColor.r, centerColor.g, centerColor.b);
  const ringRadii = [0.42, 0.78, 1, 1, 1.13];
  const ringHeights = [2.8, 2.2, 0, -5, -7];
  for (let ring = 0; ring < ringRadii.length; ring++) {
    for (let i = 0; i < segments; i++) {
      const angle = i / segments * Math.PI * 2;
      const irregular = 1 + 0.07 * Math.sin(angle * 3 + phase) + 0.045 * Math.cos(angle * 5 - phase);
      const r = radius * ringRadii[ring] * irregular;
      const y = ringHeights[ring] + (ring < 2 ? Math.sin(angle * 2 + phase) * 1.1 : 0);
      positions.push(Math.cos(angle) * r, y, Math.sin(angle) * r);
      const color = palette[ring + 1];
      colors.push(color.r, color.g, color.b);
      const next = (i + 1) % segments;
      if (ring === 0) indices.push(0, 1 + next, 1 + i);
      else {
        const a = 1 + (ring - 1) * segments + i, b = 1 + (ring - 1) * segments + next;
        const c = 1 + ring * segments + i, d = 1 + ring * segments + next;
        indices.push(a, b, c, b, d, c);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function paint(geometry: THREE.BufferGeometry, color: string): THREE.BufferGeometry {
  const c = new THREE.Color(color), count = geometry.getAttribute('position').count;
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) { colors[i * 3] = c.r; colors[i * 3 + 1] = c.g; colors[i * 3 + 2] = c.b; }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.clearGroups();
  return geometry;
}

function merged(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  // Three's primitive families have different index/UV layouts. This static
  // vertex-color batch needs only positions, normals and colors.
  const compatible = parts.map(part => {
    const geometry = part.index ? part.toNonIndexed() : part;
    geometry.deleteAttribute('uv'); return geometry;
  });
  const geometry = mergeGeometries(compatible, false)!;
  compatible.forEach((part, index) => { if (part !== parts[index]) part.dispose(); });
  parts.forEach(part => part.dispose());
  geometry.clearGroups();
  return geometry;
}

function box(parts: THREE.BufferGeometry[], x: number, y: number, z: number, w: number, h: number, d: number, color: string) {
  parts.push(paint(new THREE.BoxGeometry(w, h, d), color).translate(x, y, z));
}

function createSettlement(slot: IslandSlot): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const rng = createPrng(slot.id);
  // Small architectural silhouettes express role. They contain no residents or jobs.
  for (let i = 0; i < 9; i++) {
    const x = (i % 3 - 1) * 14, z = (Math.floor(i / 3) - 1) * 14;
    const height = slot.wing === 'coding' ? 5 + rng() * 9 : 4 + rng() * 5;
    box(parts, x, height / 2 + 2, z, 7, height, 8, i % 3 === 0 ? slot.color : '#d4ceba');
    box(parts, x, height + 2.3, z, 7.7, 0.8, 8.7, '#405956');
    for (let window = 0; window < 3; window++) box(parts, x - 2.2 + window * 2.2, height * 0.6 + 2, z + 4.05, 1.1, 1.6, 0.16, '#385653');
  }
  box(parts, 0, 0.7, -67, 12, 1, 20, '#9b8266');
  for (const x of [-5, 5]) for (const z of [-61, -72]) box(parts, x, -2, z, 0.7, 6, 0.7, '#665746');
  for (let i = 0; i < 10; i++) {
    const angle = i / 10 * Math.PI * 2;
    const x = Math.cos(angle) * 45, z = Math.sin(angle) * 45;
    box(parts, x, 3.5, z, 0.9, 4, 0.9, '#695944');
    parts.push(paint(new THREE.IcosahedronGeometry(3, 0), '#668568').translate(x, 6, z));
  }
  if (slot.wing === 'design') {
    // Open-air studio / sculptural sail canopy.
    const sail = paint(new THREE.ConeGeometry(7, 7, 4), slot.color).rotateY(Math.PI / 4).translate(34, 7, 0);
    parts.push(sail);
    box(parts, 34, 2.5, 0, 12, 1, 12, '#cfc4aa');
  } else if (slot.wing === 'marketing') {
    box(parts, -30, 9, 0, 1.5, 18, 1.5, '#665746');
    box(parts, -30, 16, 0, 12, 5, 0.8, slot.color);
  } else {
    box(parts, 32, 8, 0, 2, 16, 2, '#637570');
    parts.push(paint(new THREE.CylinderGeometry(5, 2, 1.5, 10), slot.color).rotateZ(0.6).translate(32, 17, 0));
  }
  return merged(parts);
}

function createCoastalProps(slot: IslandSlot, seed: string): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const noise = createPerlinLike2D(createPrng(seed));
  // Steps continue the coastal path to a low timber pier above the sea.
  for (let i = 0; i < 12; i++) {
    const z = 45 + i * 2.25;
    const y = Math.max(0.65, getTerrainSurfaceHeight(0, z, noise) + 0.14);
    box(parts, 0, y, z, 3.2, 0.3, 2.4, '#a58a68');
  }
  box(parts, 0, 0.4, 78, 6, 0.6, 20, '#a58a68');
  for (const x of [-2.5, 2.5]) for (const z of [70, 78, 86]) box(parts, x, -2, z, 0.5, 6, 0.5, '#675645');
  for (let i = 0; i < 11; i++) box(parts, 0, 0.73, 69 + i * 1.6, 5.9, 0.05, 0.08, '#726149');
  box(parts, -2.3, 2.1, 85, 0.25, 3.5, 0.25, '#6c6554');
  box(parts, -0.9, 3.2, 85, 2.5, 1.4, 0.1, slot.color);
  // Small coastal beacon is navigation scenery, never evidence of device health.
  const foot = getTerrainSurfaceHeight(43, 38, noise);
  parts.push(paint(new THREE.CylinderGeometry(1.4, 2, 7, 10), '#e3d9bd').translate(43, foot + 3.5, 38));
  parts.push(paint(new THREE.CylinderGeometry(2, 2, 0.6, 10), '#516c68').translate(43, foot + 7.1, 38));
  parts.push(paint(new THREE.CylinderGeometry(1.1, 1.1, 1.5, 8), '#dcc595').translate(43, foot + 8.2, 38));
  parts.push(paint(new THREE.ConeGeometry(1.8, 1.4, 10), slot.color).translate(43, foot + 9.5, 38));
  // A static sailboat gives scale to the harbor without another animation loop.
  const hull = paint(new THREE.SphereGeometry(1, 10, 6), '#ece2c7').scale(2.1, 0.75, 5).translate(8, -0.9, 80);
  parts.push(hull);
  box(parts, 8, 3.8, 80, 0.18, 10, 0.18, '#7c6b55');
  const sail = new THREE.BufferGeometry();
  sail.setAttribute('position', new THREE.Float32BufferAttribute([8, 0.8, 80, 8, 8.2, 80, 8, 0.8, 85.2, 8.02, 0.8, 80, 8.02, 0.8, 85.2, 8.02, 8.2, 80], 3));
  sail.computeVertexNormals(); parts.push(paint(sail, slot.color));
  return merged(parts);
}

function createShoreline(seed: string): THREE.BufferGeometry {
  const noise = createPerlinLike2D(createPrng(seed));
  const positions: number[] = [];
  const segments = 192;
  const edge = (angle: number) => {
    let inner = 52, outer = 88;
    for (let i = 0; i < 14; i++) {
      const radius = (inner + outer) / 2;
      if (getTerrainSurfaceHeight(Math.cos(angle) * radius, Math.sin(angle) * radius, noise) > SEA_LEVEL) inner = radius;
      else outer = radius;
    }
    return (inner + outer) / 2;
  };
  for (let i = 0; i < segments; i++) {
    // Small breaks keep the strand from becoming a perfectly drawn outline.
    if (i % 17 === 0 || i % 17 === 1) continue;
    const a = i / segments * Math.PI * 2, b = (i + 1) / segments * Math.PI * 2;
    const ra = edge(a), rb = edge(b), width = 0.3 + Math.sin(a * 9) * 0.12;
    const points = [[Math.cos(a) * ra, SEA_LEVEL + 0.035, Math.sin(a) * ra],
      [Math.cos(a) * (ra + width), SEA_LEVEL + 0.035, Math.sin(a) * (ra + width)],
      [Math.cos(b) * rb, SEA_LEVEL + 0.035, Math.sin(b) * rb],
      [Math.cos(b) * (rb + width), SEA_LEVEL + 0.035, Math.sin(b) * (rb + width)]];
    for (const index of [0, 2, 1, 1, 2, 3]) positions.push(...points[index]);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals(); return geometry;
}

export interface ArchipelagoController {
  group: THREE.Group;
  anchor(x: number, z: number, selectedId: string): void;
  stats(): { drawCalls: number; triangles: number; chunks: number };
  islandPosition(id: string): THREE.Vector3 | null;
  dispose(): void;
}

export function createArchipelago(seed: string, slots: readonly IslandSlot[]): ArchipelagoController {
  const group = new THREE.Group(); group.name = 'FleetArchipelago';
  const landMaterial = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true });
  const settlementMaterial = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true });
  const waterGeometry = new THREE.PlaneGeometry(32000, 32000);
  waterGeometry.rotateX(-Math.PI / 2);
  const waterMaterial = new THREE.MeshBasicMaterial({ color: '#87b0ac' });
  const water = new THREE.Mesh(waterGeometry, waterMaterial); water.position.y = SEA_LEVEL;
  water.name = 'OpenSea'; group.add(water);
  const harbor = new THREE.Mesh(new THREE.BufferGeometry(), settlementMaterial); harbor.name = 'IslandHarbor'; group.add(harbor);
  const foamMaterial = new THREE.MeshBasicMaterial({ color: '#dce9d7', side: THREE.DoubleSide });
  const foam = new THREE.Mesh(createShoreline(seed), foamMaterial); foam.name = 'ShoreBreak'; group.add(foam);
  let lastSelected = '';
  const fleet = new Map<string, THREE.Group>();
  for (const slot of slots) {
    const island = new THREE.Group(); island.name = slot.id; island.userData.fleetId = slot.id;
    const land = new THREE.Mesh(createIslandGeometry(slot.id, 72), landMaterial); land.name = 'DistantHeadland';
    const settlement = new THREE.Mesh(createSettlement(slot), settlementMaterial); settlement.name = 'RoleSilhouette';
    island.add(land, settlement); fleet.set(slot.id, island); group.add(island);
  }
  const chunks = new Map<string, { mesh: THREE.Mesh; x: number; z: number }>();
  let anchorX = 0, anchorZ = 0, disposed = false;
  function anchor(x: number, z: number, selectedId: string) {
    if (disposed || !Number.isFinite(x) || !Number.isFinite(z)) return;
    anchorX = x; anchorZ = z;
    const selected = slots.find(slot => slot.id === selectedId);
    if (selected) {
      if (selectedId !== lastSelected) {
        harbor.geometry.dispose(); harbor.geometry = createCoastalProps(selected, seed); lastSelected = selectedId;
      }
      const dx = selected.x - x, dz = selected.z - z;
      harbor.visible = Math.hypot(dx, dz) < 1600;
      harbor.position.set(harbor.visible ? dx : 0, 0, harbor.visible ? dz : 0);
      foam.visible = harbor.visible; foam.position.copy(harbor.position);
    }
    for (const slot of slots) {
      const island = fleet.get(slot.id)!;
      const dx = slot.x - x, dz = slot.z - z;
      island.visible = slot.id !== selectedId && Math.hypot(dx, dz) < 1600;
      island.position.set(island.visible ? dx : 0, 0, island.visible ? dz : 0);
    }
    const keys = chunkKeysAround(x, z), desired = new Set(keys);
    for (const [key, chunk] of chunks) if (!desired.has(key)) {
      group.remove(chunk.mesh); chunk.mesh.geometry.dispose(); chunks.delete(key);
    }
    for (const key of keys) {
      if (!chunks.has(key)) {
        const [cx, cz] = key.split(':').map(Number);
        const originX = cx * CHUNK_SIZE, originZ = cz * CHUNK_SIZE;
        const parts = sceneryForChunk(seed, cx, cz, slots).map(spec => createIslandGeometry(spec.seed, spec.radius).translate(spec.x - originX, -1, spec.z - originZ));
        // Empty ocean chunks still have a cache entry, with no submitted geometry.
        const geometry = parts.length ? merged(parts) : new THREE.BufferGeometry();
        const mesh = new THREE.Mesh(geometry, landMaterial);
        mesh.name = 'UnmappedScenery'; mesh.visible = parts.length > 0;
        mesh.userData.sceneryOnly = true; group.add(mesh);
        chunks.set(key, { mesh, x: originX, z: originZ });
      }
      const chunk = chunks.get(key)!;
      chunk.mesh.position.set(chunk.x - x, 0, chunk.z - z);
    }
    group.updateMatrixWorld(true);
  }
  return {
    group, anchor,
    stats() {
      let drawCalls = 0, triangles = 0;
      group.traverseVisible(object => {
        if (object instanceof THREE.Mesh && object.geometry.getAttribute('position')) {
          drawCalls++; triangles += object.geometry.index ? object.geometry.index.count / 3 : object.geometry.getAttribute('position').count / 3;
        }
      });
      return { drawCalls, triangles, chunks: chunks.size };
    },
    islandPosition(id: string) {
      const slot = slots.find(slot => slot.id === id);
      return slot ? new THREE.Vector3(slot.x - anchorX, 12, slot.z - anchorZ) : null;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      group.traverse(object => { if (object instanceof THREE.Mesh) object.geometry.dispose(); });
      landMaterial.dispose(); settlementMaterial.dispose(); waterMaterial.dispose(); foamMaterial.dispose();
      group.clear(); chunks.clear();
    }
  };
}
