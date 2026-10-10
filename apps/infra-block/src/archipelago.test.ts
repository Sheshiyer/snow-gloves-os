import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { chunkKeysAround, createArchipelago, createIslandGeometry, sceneryForChunk, fitCameraDistance, CHUNK_SIZE, SEA_LEVEL } from './archipelago';
import { createEnvironment } from './environment';

const slots = [
  { id: 'mac-coding-1', name: 'Mac Coding 01', wing: 'coding', x: -180, z: -110, color: '#89aaad' },
  { id: 'mac-coding-2', name: 'Mac Coding 02', wing: 'coding', x: 180, z: -110, color: '#96b3aa' },
  { id: 'mac-creative', name: 'Mac Creative', wing: 'design', x: -180, z: 180, color: '#d7a998' },
  { id: 'mac-marketing', name: 'Mac Marketing', wing: 'marketing', x: 180, z: 180, color: '#d7be7c' }
];

describe('Fleet archipelago geometry', () => {
  it.each([
    { width: 1309, height: 818, top: 260, bottom: 92 },
    { width: 390, height: 844, top: 425, bottom: 225 },
    { width: 844, height: 390, top: 138, bottom: 94 }
  ])('fits complete four-island coast bounds inside HUD margins at $width x $height', viewport => {
    const camera = new THREE.PerspectiveCamera(35, viewport.width / viewport.height, 10, 50000);
    camera.setViewOffset(viewport.width, viewport.height, 0, (viewport.bottom - viewport.top) / 2, viewport.width, viewport.height);
    const bounds = new THREE.Box3(new THREE.Vector3(-265, -8, -235), new THREE.Vector3(265, 22, 235));
    const direction = new THREE.Vector3(0.05, 1, 0.25).normalize();
    const limits = { top: 1 - 2 * viewport.top / viewport.height, bottom: -1 + 2 * viewport.bottom / viewport.height, horizontal: 0.91 };
    const distance = fitCameraDistance(camera, bounds, direction, new THREE.Vector3(), 800, limits);
    camera.position.copy(direction).multiplyScalar(distance); camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
    for (const x of [-265, 265]) for (const y of [-8, 22]) for (const z of [-235, 235]) {
      const point = new THREE.Vector3(x, y, z).project(camera);
      expect(Math.abs(point.x)).toBeLessThanOrEqual(limits.horizontal);
      expect(point.y).toBeLessThanOrEqual(limits.top);
      expect(point.y).toBeGreaterThanOrEqual(limits.bottom);
    }
    expect(distance).toBeLessThan(12000);
  });

  it('fits the full town coastline and pier independently of the street camera', () => {
    const camera = new THREE.PerspectiveCamera(35, 1309 / 818, 1, 50000);
    const limits = { top: 0.38, bottom: -0.77, horizontal: 0.91 };
    const direction = new THREE.Vector3(35, 37, 41).normalize(), target = new THREE.Vector3(0, 3, 0);
    const coast = new THREE.Box3(new THREE.Vector3(-85, -8, -85), new THREE.Vector3(85, 16, 90));
    const street = new THREE.Box3(new THREE.Vector3(-26.3, -1.6, -26.3), new THREE.Vector3(26.3, 8, 26.3));
    const overview = fitCameraDistance(camera, coast, direction, target, 240, limits);
    const city = fitCameraDistance(camera, street, direction, target, 60, { top: 1.04, bottom: -1.04, horizontal: 1.08 });
    expect(overview).toBeGreaterThan(city * 2);
    camera.position.copy(target).addScaledVector(direction, overview); camera.lookAt(target); camera.updateMatrixWorld();
    for (const x of [-85, 85]) for (const y of [-8, 16]) for (const z of [-85, 90]) {
      const point = new THREE.Vector3(x, y, z).project(camera);
      expect(point.y).toBeLessThanOrEqual(limits.top);
      expect(point.y).toBeGreaterThanOrEqual(limits.bottom);
    }
  });
  it('creates irregular coastline with raised land and submerged cliff volume deterministically', () => {
    const a = createIslandGeometry('headland-a', 72), b = createIslandGeometry('headland-a', 72);
    expect(a.getAttribute('position').array).toEqual(b.getAttribute('position').array);
    const position = a.getAttribute('position');
    let minY = Infinity, maxY = -Infinity;
    const shoreRadii = new Set<number>();
    for (let i = 0; i < position.count; i++) {
      minY = Math.min(minY, position.getY(i)); maxY = Math.max(maxY, position.getY(i));
      if (position.getY(i) === 0) shoreRadii.add(Math.round(Math.hypot(position.getX(i), position.getZ(i))));
    }
    expect(minY).toBeLessThan(SEA_LEVEL - 3);
    expect(maxY).toBeGreaterThan(2);
    expect(shoreRadii.size).toBeGreaterThan(5);
    expect(a.index!.count / 3).toBeLessThan(400);
    a.dispose(); b.dispose();
  });

  it('uses exactly nine deterministic logical chunks and leaves mapped Mac clearances empty', () => {
    expect(chunkKeysAround(0, 0)).toHaveLength(9);
    expect(new Set(chunkKeysAround(0, 0)).size).toBe(9);
    expect(chunkKeysAround(-1, -1)).toContain('-2:-2');
    for (const key of chunkKeysAround(0, 0)) {
      const [x, z] = key.split(':').map(Number);
      const a = sceneryForChunk('world', x, z, slots), b = sceneryForChunk('world', x, z, slots);
      expect(a).toEqual(b);
      for (const islet of a) for (const slot of slots) expect(Math.hypot(islet.x - slot.x, islet.z - slot.z)).toBeGreaterThanOrEqual(150 + islet.radius);
    }
  });

  it('rebases far exploration into bounded render coordinates and never clones a detailed town', () => {
    const arch = createArchipelago('world', slots);
    for (const [x, z] of [[-180, -110], [0, 35], [5_200_021, -9_880_011], [-180, -110]]) {
      arch.anchor(x, z, slots[0].id);
      expect(arch.stats().chunks).toBe(9);
      for (const object of arch.group.children) {
        expect(Math.abs(object.position.x)).toBeLessThanOrEqual(CHUNK_SIZE * 3.1);
        expect(Math.abs(object.position.z)).toBeLessThanOrEqual(CHUNK_SIZE * 3.1);
      }
      expect(arch.group.getObjectByName(slots[0].id)!.visible).toBe(false);
      expect(arch.group.getObjectByName('DetailedTown')).toBeUndefined();
    }
    expect(arch.islandPosition('mac-marketing')!.x).toBe(360);
    expect(arch.islandPosition('not-a-mac')).toBeNull();
    arch.dispose();
  });

  it('keeps combined scenery and grounded environment under 35k triangles and 40 additional submissions for every selected role', () => {
    const environment = createEnvironment('budget-world');
    const arch = createArchipelago('budget-world', slots);
    for (const slot of slots) {
      arch.anchor(slot.x, slot.z, slot.id);
      const stats = arch.stats();
      console.info(JSON.stringify({ receipt: 'archipelago-budget', island: slot.id, ...stats, combinedTriangles: stats.triangles + environment.userData.environmentalStats.triangles }));
      expect(stats.drawCalls).toBeLessThanOrEqual(40);
      expect(stats.triangles + environment.userData.environmentalStats.triangles).toBeLessThanOrEqual(35000);
      expect(stats.chunks).toBe(9);
      expect(arch.group.getObjectByName(slot.id)!.visible).toBe(false);
      expect(arch.group.getObjectByName('IslandHarbor')).toBeDefined();
      expect(arch.group.getObjectByName('ShoreBreak')).toBeDefined();
    }
    arch.dispose();
  });

  it('disposes evicted chunk geometry once and final resources once with idempotent disposal', () => {
    const arch = createArchipelago('disposal-world', slots); arch.anchor(-180, -110, slots[0].id);
    const chunk = arch.group.children.find(object => object.name === 'UnmappedScenery') as THREE.Mesh;
    const evicted = vi.spyOn(chunk.geometry, 'dispose');
    arch.anchor(5200, 5200, slots[0].id);
    expect(evicted).toHaveBeenCalledTimes(1);
    const geometrySpies: ReturnType<typeof vi.spyOn>[] = [];
    const materials = new Set<THREE.Material>();
    arch.group.traverse(object => {
      if (object instanceof THREE.Mesh) {
        geometrySpies.push(vi.spyOn(object.geometry, 'dispose'));
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) materials.add(material);
      }
    });
    const materialSpies = [...materials].map(material => vi.spyOn(material, 'dispose'));
    arch.dispose(); arch.dispose(); arch.anchor(0, 0, slots[0].id);
    for (const spy of geometrySpies) expect(spy).toHaveBeenCalledTimes(1);
    for (const spy of materialSpies) expect(spy).toHaveBeenCalledTimes(1);
    expect(arch.group.children).toHaveLength(0);
  });
});
