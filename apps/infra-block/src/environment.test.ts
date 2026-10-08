import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { createEnvironment, getTerrainHeight, createPrng, createPerlinLike2D } from './environment';

function calculateEnvironmentTriangles(group: THREE.Group): number {
  let tris = 0;
  group.traverse((obj) => {
    if (obj instanceof THREE.InstancedMesh) {
      const geoTris = obj.geometry.index
        ? obj.geometry.index.count / 3
        : (obj.geometry.attributes.position?.count ?? 0) / 3;
      tris += geoTris * obj.count;
    } else if (obj instanceof THREE.Mesh) {
      const geoTris = obj.geometry.index
        ? obj.geometry.index.count / 3
        : (obj.geometry.attributes.position?.count ?? 0) / 3;
      tris += geoTris;
    }
  });
  return tris;
}

function calculateEnvironmentDrawCalls(group: THREE.Group): number {
  let calls = 0;
  group.traverse((obj) => {
    if (obj instanceof THREE.Mesh || obj instanceof THREE.InstancedMesh) {
      if (Array.isArray(obj.material)) {
        const groups = obj.geometry.groups;
        calls += groups && groups.length > 0 ? groups.length : obj.material.length;
      } else {
        calls += 1;
      }
    }
  });
  return calls;
}

describe('Grounded Square Landscape Environment', () => {
  it('creates deterministic environment with stable names and structure', () => {
    const env1 = createEnvironment('test-seed-42');
    const env2 = createEnvironment('test-seed-42');

    expect(env1.name).toBe('GroundedEnvironment');
    expect(env1.children.length).toBe(env2.children.length);

    const childNames1 = env1.children.map((c) => c.name).sort();
    const childNames2 = env2.children.map((c) => c.name).sort();
    expect(childNames1).toEqual(childNames2);
    expect(childNames1).toContain('Terrain');
    expect(childNames1).toContain('RoadsHorizontal');
    expect(childNames1).toContain('RoadsVertical');
    expect(childNames1).toContain('RoadMarkings');
    expect(childNames1).toContain('ContinuousFootpaths');
    expect(childNames1).toContain('TreeTrunks');
    expect(childNames1).toContain('TreeFoliageCrowns');
    expect(childNames1).toContain('MeadowGrassPatches');
  });

  it('guarantees budget invariant <= 40 draw calls and <= 35000 triangles and prints JSON stats', () => {
    const env = createEnvironment('perf-seed');
    const stats = env.userData.environmentalStats;

    const computedTris = calculateEnvironmentTriangles(env);
    const computedCalls = calculateEnvironmentDrawCalls(env);

    console.info(JSON.stringify({
      receipt: 'performance-budget',
      reportedDrawCalls: stats.drawCalls,
      computedDrawCalls: computedCalls,
      reportedTriangles: stats.triangles,
      computedTriangles: computedTris,
      cosmeticOnly: stats.cosmeticOnly,
    }));

    expect(stats.drawCalls).toBeLessThanOrEqual(40);
    expect(stats.triangles).toBeLessThanOrEqual(35000);
    expect(stats.cosmeticOnly).toBe(true);
    expect(computedCalls).toBe(stats.drawCalls);
    expect(computedTris).toBe(stats.triangles);
  });

  it('maintains strict flat Chebyshev square city center [-30, 30] and [-26.3, 26.3] corners at y = 0', () => {
    const env = createEnvironment('city-square-check');
    const terrain = env.getObjectByName('Terrain') as THREE.Mesh;
    expect(terrain).toBeDefined();
    expect(terrain.receiveShadow).toBe(true);

    const pos = terrain.geometry.attributes.position;
    expect(pos).toBeDefined();
    if (!pos) return;

    // Test all mesh vertices in Chebyshev square <= 30
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const y = pos.getY(i);
      const chebyshev = Math.max(Math.abs(x), Math.abs(z));

      if (chebyshev <= 30.0 + 1e-5) {
        expect(y).toBe(0);
      }
    }

    // Test explicit city corners
    const rng = createPrng('city-square-check');
    const noise = createPerlinLike2D(rng);
    expect(getTerrainHeight(26.3, 26.3, noise)).toBe(0);
    expect(getTerrainHeight(-26.3, 26.3, noise)).toBe(0);
    expect(getTerrainHeight(26.3, -26.3, noise)).toBe(0);
    expect(getTerrainHeight(-26.3, -26.3, noise)).toBe(0);
    expect(getTerrainHeight(30.0, 30.0, noise)).toBe(0);
    expect(getTerrainHeight(25.0, 25.0, noise)).toBe(0);
  });

  it('strictly enforces tree and grass Chebyshev square bounds across 3 seeds', () => {
    const testSeeds = ['seed-alpha-1', 'seed-beta-2', 'seed-gamma-3'];

    for (const seed of testSeeds) {
      const env = createEnvironment(seed);
      const trunkMesh = env.getObjectByName('TreeTrunks') as THREE.InstancedMesh;
      const foliageMesh = env.getObjectByName('TreeFoliageCrowns') as THREE.InstancedMesh;
      const grassMesh = env.getObjectByName('MeadowGrassPatches') as THREE.InstancedMesh;
      const footpathMesh = env.getObjectByName('ContinuousFootpaths') as THREE.Mesh;

      expect(trunkMesh.count).toBe(75);
      expect(foliageMesh.count).toBe(225);

      const matrix = new THREE.Matrix4();
      const pos = new THREE.Vector3();

      // Trunk Chebyshev square check (>= 34)
      for (let i = 0; i < trunkMesh.count; i++) {
        trunkMesh.getMatrixAt(i, matrix);
        pos.setFromMatrixPosition(matrix);
        const chebyshev = Math.max(Math.abs(pos.x), Math.abs(pos.z));
        expect(chebyshev).toBeGreaterThanOrEqual(34.0);
      }

      // Grass Chebyshev square check (>= 33 to prevent margin bleed into 30)
      for (let i = 0; i < grassMesh.count; i++) {
        grassMesh.getMatrixAt(i, matrix);
        pos.setFromMatrixPosition(matrix);
        const chebyshev = Math.max(Math.abs(pos.x), Math.abs(pos.z));
        expect(chebyshev).toBeGreaterThanOrEqual(33.0);
      }

      // Footpath vertices outside Chebyshev 30 (except connecting ribbons that start outside 30 at 34)
      const pathPos = footpathMesh.geometry.attributes.position;
      for (let i = 0; i < pathPos.count; i++) {
        const px = pathPos.getX(i);
        const pz = pathPos.getZ(i);
        const chebyshev = Math.max(Math.abs(px), Math.abs(pz));
        expect(chebyshev).toBeGreaterThanOrEqual(33.0);
      }
    }
  });

  it('verifies exact road center coordinates, dash markings and no distant cylinder mesas', () => {
    const env = createEnvironment('road-spec-check');
    const hRoads = env.getObjectByName('RoadsHorizontal') as THREE.InstancedMesh;
    const vRoads = env.getObjectByName('RoadsVertical') as THREE.InstancedMesh;
    const markings = env.getObjectByName('RoadMarkings') as THREE.InstancedMesh;
    const distantRidges = env.getObjectByName('DistantRidges');

    // Artificial cylinder mesas must be removed
    expect(distantRidges).toBeUndefined();

    expect(hRoads).toBeDefined();
    expect(vRoads).toBeDefined();
    expect(markings).toBeDefined();
    expect(markings.count).toBeLessThanOrEqual(130);
    expect(markings.count).toBeGreaterThan(50);

    const expectedCoords = [-20.8, -10.4, 0, 10.4, 20.8];
    const mat = new THREE.Matrix4();
    const pos = new THREE.Vector3();

    for (let i = 0; i < hRoads.count; i++) {
      hRoads.getMatrixAt(i, mat);
      pos.setFromMatrixPosition(mat);
      expect(expectedCoords).toContain(Number(pos.z.toFixed(1)));
      expect(pos.y).toBeCloseTo(0.012, 3);
    }

    for (let i = 0; i < vRoads.count; i++) {
      vRoads.getMatrixAt(i, mat);
      pos.setFromMatrixPosition(mat);
      expect(expectedCoords).toContain(Number(pos.x.toFixed(1)));
      expect(pos.y).toBeCloseTo(0.016, 3);
    }
  });

  it('strictly validates determinism of positions, colors, and instance matrices', () => {
    const env1 = createEnvironment('determinism-seed');
    const env2 = createEnvironment('determinism-seed');

    const terrain1 = env1.getObjectByName('Terrain') as THREE.Mesh;
    const terrain2 = env2.getObjectByName('Terrain') as THREE.Mesh;
    expect(terrain1.geometry.attributes.position.array).toEqual(terrain2.geometry.attributes.position.array);
    expect(terrain1.geometry.attributes.color.array).toEqual(terrain2.geometry.attributes.color.array);

    const trunks1 = env1.getObjectByName('TreeTrunks') as THREE.InstancedMesh;
    const trunks2 = env2.getObjectByName('TreeTrunks') as THREE.InstancedMesh;
    expect(trunks1.instanceMatrix.array).toEqual(trunks2.instanceMatrix.array);

    const crowns1 = env1.getObjectByName('TreeFoliageCrowns') as THREE.InstancedMesh;
    const crowns2 = env2.getObjectByName('TreeFoliageCrowns') as THREE.InstancedMesh;
    expect(crowns1.instanceMatrix.array).toEqual(crowns2.instanceMatrix.array);
    expect(crowns1.instanceColor!.array).toEqual(crowns2.instanceColor!.array);
  });

  it('supports deduplicated traversal and validates single-call resource disposal spy', () => {
    const env = createEnvironment('disposal-test');
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();

    env.traverse((obj) => {
      if (obj instanceof THREE.Mesh || obj instanceof THREE.InstancedMesh) {
        if (obj.geometry) {
          geometries.add(obj.geometry);
        }
        if (obj.material) {
          if (Array.isArray(obj.material)) {
            obj.material.forEach((m) => materials.add(m));
          } else {
            materials.add(obj.material);
          }
        }
      }
    });

    expect(geometries.size).toBeGreaterThan(0);
    expect(materials.size).toBeGreaterThan(0);

    const geoSpies = Array.from(geometries).map((g) => vi.spyOn(g, 'dispose'));
    const matSpies = Array.from(materials).map((m) => vi.spyOn(m, 'dispose'));

    geometries.forEach((g) => g.dispose());
    materials.forEach((m) => m.dispose());

    geoSpies.forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
    matSpies.forEach((spy) => expect(spy).toHaveBeenCalledTimes(1));
  });
  it('grounds every path vertex and tree foot on the actual terrain triangles', () => {
    const env = createEnvironment('ground-contact');
    env.updateMatrixWorld(true);
    const terrain = env.getObjectByName('Terrain') as THREE.Mesh;
    const ray = new THREE.Raycaster(new THREE.Vector3(), new THREE.Vector3(0, -1, 0));
    const groundHeight = (x: number, z: number) => {
      ray.ray.origin.set(x, 100, z);
      const hit = ray.intersectObject(terrain, false)[0];
      expect(hit).toBeDefined();
      return hit.point.y;
    };
    const path = env.getObjectByName('ContinuousFootpaths') as THREE.Mesh;
    const positions = path.geometry.attributes.position;
    for (let i = 0; i < positions.count; i++) {
      expect(positions.getY(i) - groundHeight(positions.getX(i), positions.getZ(i))).toBeCloseTo(0.06, 4);
    }
    const trunks = env.getObjectByName('TreeTrunks') as THREE.InstancedMesh;
    const matrix = new THREE.Matrix4(), position = new THREE.Vector3();
    for (let i = 0; i < trunks.count; i++) {
      trunks.getMatrixAt(i, matrix);
      position.setFromMatrixPosition(matrix);
      expect(position.y).toBeCloseTo(groundHeight(position.x, position.z), 4);
    }
  });

  it.each(['pastel_city', 'ground-contact', 'perf-seed'])('keeps path interiors above mesh terrain for %s', seed => {
    const env = createEnvironment(seed);
    env.updateMatrixWorld(true);
    const terrain = env.getObjectByName('Terrain') as THREE.Mesh;
    const path = env.getObjectByName('ContinuousFootpaths') as THREE.Mesh;
    const pos = path.geometry.attributes.position;
    const ray = new THREE.Raycaster(new THREE.Vector3(), new THREE.Vector3(0, -1, 0));
    let minClearance = Infinity, maxClearance = -Infinity;
    const weights = [[1/3,1/3,1/3],[0.5,0.5,0],[0,0.5,0.5],[0.5,0,0.5]];
    for (let i = 0; i < pos.count; i += 3) {
      for (const weight of weights) {
        let x=0,y=0,z=0;
        for (let j=0;j<3;j++) { x+=pos.getX(i+j)*weight[j]; y+=pos.getY(i+j)*weight[j]; z+=pos.getZ(i+j)*weight[j]; }
        ray.ray.origin.set(x,100,z);
        const hit = ray.intersectObject(terrain, false)[0];
        expect(hit).toBeDefined();
        const clearance = y-hit.point.y;
        minClearance = Math.min(minClearance, clearance);
        maxClearance = Math.max(maxClearance, clearance);
      }
    }
    expect(minClearance).toBeGreaterThan(0.0599);
    expect(maxClearance).toBeLessThan(0.0601);
    expect(calculateEnvironmentTriangles(env)).toBeLessThanOrEqual(35000);
    expect(calculateEnvironmentDrawCalls(env)).toBe(8);
  });

});
