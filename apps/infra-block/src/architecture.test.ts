import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import * as THREE from 'three';
import { createArchitecture as buildArchitecture } from './architecture';
const allocated: ReturnType<typeof buildArchitecture>[] = [];
const createArchitecture = (...args: Parameters<typeof buildArchitecture>) => { const value = buildArchitecture(...args); allocated.push(value); return value; };
afterEach(() => {
  for (const value of allocated.splice(0)) {
    const geometries = new Set<THREE.BufferGeometry>();
    value.bodyMesh.traverse(object => { if (object instanceof THREE.Mesh) geometries.add(object.geometry); });
    geometries.forEach(geometry => geometry.dispose());
    value.materials.forEach(material => { (material as THREE.MeshStandardMaterial).map?.dispose(); material.dispose(); });
  }
  vi.unstubAllGlobals();
});
import type { BuildingState, InfraNode } from './contracts';
import { createGame } from './game';

function makeBuilding(index: number, w = 6, d = 8, h = 12): BuildingState {
  return {
    id: `bld_${index}`,
    x: index * 15,
    z: index * 10,
    width: w,
    depth: d,
    height: h,
    floors: 3,
    health: 100,
    maxHealth: 100,
    destroyed: false,
  };
}

function makeNode(id: string, color = '#2288cc'): InfraNode {
  return {
    id,
    name: 'Node ' + id,
    short: 'N_' + id,
    layer: 'runtime',
    color,
    summary: '',
    detail: '',
    sources: [],
    links: [],
    evidence: 'local',
    evidenceNote: '',
  };
}

function stubCanvas() {
  vi.stubGlobal('document', {});
  document.createElement = vi.fn((tag: string) => {
    if (tag === 'canvas') {
      return {
        width: 512,
        height: 512,
        getContext: () => ({
          fillStyle: '',
          strokeStyle: '',
          lineWidth: 1,
          font: '',
          textAlign: '',
          fillRect: vi.fn(),
          strokeRect: vi.fn(),
          fillText: vi.fn(),
          beginPath: vi.fn(),
          moveTo: vi.fn(),
          lineTo: vi.fn(),
          stroke: vi.fn(),
        }),
      } as any;
    }
    return {} as any;
  }) as any;
}

describe('Architecture Module', () => {
  beforeEach(() => {
    stubCanvas();
  });

  it('creates architecture with bodyMesh, bounds <= bs dimensions, and total meshes <= 12', () => {
    for (let i = 0; i < 16; i++) {
      const bs = createGame('architecture-budget', 'munch').buildings[i];
      const node = makeNode(`n_${i}`);
      const { bodyMesh, materials } = createArchitecture(bs, node, i);

      expect(bodyMesh).toBeInstanceOf(THREE.Mesh);
      expect(materials.length).toBeGreaterThanOrEqual(1);

      let meshCount = 0;
      bodyMesh.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          meshCount++;
          for (const material of Array.isArray(child.material) ? child.material : [child.material]) expect(materials).toContain(material);
        }
      });
      expect(meshCount).toBeLessThanOrEqual(12);
      const bounds = new THREE.Box3().setFromObject(bodyMesh);
      expect(bounds.min.y).toBeCloseTo(0, 4);
      expect(bounds.max.y).toBeCloseTo(bs.height, 4);
      expect(bounds.getSize(new THREE.Vector3()).x).toBeCloseTo(bs.width, 4);
      expect(bounds.getSize(new THREE.Vector3()).z).toBeCloseTo(bs.depth, 4);

      // Verify materials rough/metal properties
      for (const m of materials) {
        const std = m as THREE.MeshStandardMaterial;
        expect(std.roughness).toBeGreaterThanOrEqual(0.8);
        expect(std.metalness).toBeLessThanOrEqual(0.12);
      }
    }
  });

  it('correctly maps roof styles for modulo 4 and adheres to exact dimensions', () => {
    const expectedNames = ['roof_gable', 'roof_monopitch', 'roof_flat_slab', 'roof_hipped'];
    for (let i = 0; i < 4; i++) {
      const bs = makeBuilding(i, 6, 8, 10);
      const { bodyMesh } = createArchitecture(bs, undefined, i);

      const childNames = bodyMesh.children.map((c) => c.name);
      expect(childNames).toContain(expectedNames[i]);

      // Place bodyMesh at bs.height / 2 in world coordinates
      const container = new THREE.Group();
      container.add(bodyMesh);
      expect(bodyMesh.position.y).toBe(bs.height / 2);
      bodyMesh.updateMatrixWorld(true);

      const box = new THREE.Box3().setFromObject(container);
      const eps = 0.001;
      expect(box.min.y).toBeGreaterThanOrEqual(-eps);
      expect(box.max.y).toBeLessThanOrEqual(bs.height + eps);
      expect(box.max.x - box.min.x).toBeLessThanOrEqual(bs.width + eps);
      expect(box.max.z - box.min.z).toBeLessThanOrEqual(bs.depth + eps);
    }
  });

  it('handles missing canvas 2d context gracefully without throwing', () => {
    document.createElement = vi.fn(() => ({
      width: 512,
      height: 512,
      getContext: () => null,
    })) as any;

    const bs = makeBuilding(0);
    expect(() => {
      const { bodyMesh, materials } = createArchitecture(bs, undefined, 0);
      expect(bodyMesh).toBeDefined();
      expect(materials.length).toBe(3);
    }).not.toThrow();
  });

  it('contains max 1 CanvasTexture of size <= 512 per building', () => {
    const bs = makeBuilding(1);
    const { materials } = createArchitecture(bs, makeNode('atlas_test'), 0);
    const textures = materials
      .map((m) => (m as THREE.MeshStandardMaterial).map)
      .filter((t): t is THREE.Texture => !!t);

    expect(textures.length).toBeLessThanOrEqual(1);
    if (textures.length === 1) {
      const img = textures[0].image;
      expect(img.width).toBeLessThanOrEqual(512);
      expect(img.height).toBeLessThanOrEqual(512);
    }
  });
});

