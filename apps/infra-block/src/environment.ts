import * as THREE from 'three';
import * as BufferGeometryUtils from 'three/examples/jsm/utils/BufferGeometryUtils.js';

export interface EnvironmentalStats {
  drawCalls: number;
  triangles: number;
  cosmeticOnly: boolean;
}

export interface GroundedEnvironmentGroup extends THREE.Group {
  userData: {
    environmentalStats: EnvironmentalStats;
    seed: string;
    bounds: {
      size: number;
      citySquareHalf: number;
      terrainStartSquare: number;
    };
    [key: string]: unknown;
  };
}

/**
 * Deterministic pseudo-random number generator (Mulberry32) seeded by a string.
 */
export function createPrng(seedStr: string): () => number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < seedStr.length; i++) {
    h = Math.imul(h ^ seedStr.charCodeAt(i), 16777619);
  }
  let state = h >>> 0;
  return function next(): number {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Deterministic 2D value noise for terrain elevation and color blending.
 */
export function createPerlinLike2D(rng: () => number): (x: number, z: number) => number {
  const perm: number[] = [];
  for (let i = 0; i < 256; i++) {
    perm[i] = i;
  }
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    const temp = perm[i] ?? 0;
    perm[i] = perm[j] ?? 0;
    perm[j] = temp;
  }
  const p = [...perm, ...perm];

  function fade(t: number): number {
    return t * t * t * (t * (t * 6 - 15) + 10);
  }

  function grad(hash: number, x: number, y: number): number {
    const h = hash & 3;
    const u = h < 2 ? x : y;
    const v = h < 2 ? y : x;
    return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
  }

  return function sample(x: number, z: number): number {
    const X = Math.floor(x) & 255;
    const Z = Math.floor(z) & 255;
    const xf = x - Math.floor(x);
    const zf = z - Math.floor(z);
    const u = fade(xf);
    const v = fade(zf);

    const pX = p[X] ?? 0;
    const pX1 = p[X + 1] ?? 0;
    const aa = p[pX + Z] ?? 0;
    const ab = p[pX + Z + 1] ?? 0;
    const ba = p[pX1 + Z] ?? 0;
    const bb = p[pX1 + Z + 1] ?? 0;

    const x1 = THREE.MathUtils.lerp(grad(aa, xf, zf), grad(ba, xf - 1, zf), u);
    const x2 = THREE.MathUtils.lerp(grad(ab, xf, zf - 1), grad(bb, xf - 1, zf - 1), u);
    return THREE.MathUtils.lerp(x1, x2, v);
  };
}

const ROAD_COORDINATES = [-20.8, -10.4, 0, 10.4, 20.8] as const;
const ROAD_WIDTH = 3.3;
const ROAD_LENGTH = 52.6;
const CITY_SQUARE_HALF = 26.3;
const TERRAIN_OUTER_SQUARE = 30.0;
const GROUND_SIZE = 240;
const GROUND_SEGMENTS = 48; // Grid step is 240 / 48 = 5.0, cleanly aligning vertex bounds at multiples of 5 (e.g. -30, -25, 25, 30)

/**
 * Calculates terrain height at (x, z) ensuring flat square city center [ -30.0, 30.0 ] at y = 0.
 * Uses Chebyshev distance max(abs(x), abs(z)).
 */
export function getTerrainHeight(x: number, z: number, noiseFn: (x: number, z: number) => number): number {
  const chebyshev = Math.max(Math.abs(x), Math.abs(z));
  if (chebyshev <= TERRAIN_OUTER_SQUARE) {
    return 0;
  }
  const ramp = Math.min(1.0, (chebyshev - TERRAIN_OUTER_SQUARE) / 25.0);
  const n1 = noiseFn(x * 0.03, z * 0.03) * 6.5;
  const n2 = noiseFn(x * 0.08 + 12.3, z * 0.08 + 45.6) * 2.2;
  const rawElevation = n1 + n2;
  return rawElevation * ramp;
}

/** Exact barycentric height of the same indexed PlaneGeometry triangles. */
export function getTerrainSurfaceHeight(x: number, z: number, noise: (x: number, z: number) => number): number {
  const step = GROUND_SIZE / GROUND_SEGMENTS;
  const half = GROUND_SIZE / 2;
  const gx = Math.max(0, Math.min(GROUND_SEGMENTS, (x + half) / step));
  const gz = Math.max(0, Math.min(GROUND_SEGMENTS, (z + half) / step));
  const ix = Math.min(GROUND_SEGMENTS - 1, Math.floor(gx));
  const iz = Math.min(GROUND_SEGMENTS - 1, Math.floor(gz));
  const tx = gx - ix, tz = gz - iz;
  const x0 = ix * step - half, z0 = iz * step - half;
  const h00 = getTerrainHeight(x0, z0, noise);
  const h10 = getTerrainHeight(x0 + step, z0, noise);
  const h01 = getTerrainHeight(x0, z0 + step, noise);
  const h11 = getTerrainHeight(x0 + step, z0 + step, noise);
  return tx + tz <= 1
    ? h00 + (h10 - h00) * tx + (h01 - h00) * tz
    : h11 + (h01 - h11) * (1 - tx) + (h10 - h11) * (1 - tz);
}

function conformPathGeometry(source: THREE.BufferGeometry, noise: (x: number, z: number) => number): THREE.BufferGeometry {
  type P2 = [number, number];
  const clipPoly = (poly: P2[], clipTri: [P2, P2, P2]): P2[] => {
    const cross = (a: P2, b: P2, p: P2) => (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    const ccw = cross(clipTri[0], clipTri[1], clipTri[2]) >= 0 ? 1 : -1;
    let out = poly;
    for (let i = 0; i < 3; i++) {
      const a = clipTri[i], b = clipTri[(i + 1) % 3];
      const input = out;
      out = [];
      if (!input.length) break;
      for (let j = 0; j < input.length; j++) {
        const curr = input[j], prev = input[(j + input.length - 1) % input.length];
        const currIn = cross(a, b, curr) * ccw >= -1e-7;
        const prevIn = cross(a, b, prev) * ccw >= -1e-7;
        if (currIn) {
          if (!prevIn) {
            const dx1 = b[0] - a[0], dz1 = b[1] - a[1];
            const dx2 = curr[0] - prev[0], dz2 = curr[1] - prev[1];
            const denom = dx1 * dz2 - dz1 * dx2;
            const t = Math.abs(denom) > 1e-9 ? ((prev[0] - a[0]) * dz2 - (prev[1] - a[1]) * dx2) / denom : 0;
            out.push([a[0] + t * dx1, a[1] + t * dz1]);
          }
          out.push(curr);
        } else if (prevIn) {
          const dx1 = b[0] - a[0], dz1 = b[1] - a[1];
          const dx2 = curr[0] - prev[0], dz2 = curr[1] - prev[1];
          const denom = dx1 * dz2 - dz1 * dx2;
          const t = Math.abs(denom) > 1e-9 ? ((prev[0] - a[0]) * dz2 - (prev[1] - a[1]) * dx2) / denom : 0;
          out.push([a[0] + t * dx1, a[1] + t * dz1]);
        }
      }
    }
    return out;
  };

  const pos = source.getAttribute('position');
  const idx = source.getIndex();
  const triCount = idx ? idx.count / 3 : pos.count / 3;
  const outCoords: number[] = [];

  for (let t = 0; t < triCount; t++) {
    const i0 = idx ? idx.getX(t * 3) : t * 3;
    const i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
    const p0: P2 = [pos.getX(i0), pos.getZ(i0)];
    const p1: P2 = [pos.getX(i1), pos.getZ(i1)];
    const p2: P2 = [pos.getX(i2), pos.getZ(i2)];

    const minX = Math.min(p0[0], p1[0], p2[0]), maxX = Math.max(p0[0], p1[0], p2[0]);
    const minZ = Math.min(p0[1], p1[1], p2[1]), maxZ = Math.max(p0[1], p1[1], p2[1]);
    const cMinX = Math.max(0, Math.min(47, Math.floor((minX + 120) / 5)));
    const cMaxX = Math.max(0, Math.min(47, Math.floor((maxX + 120) / 5)));
    const cMinZ = Math.max(0, Math.min(47, Math.floor((minZ + 120) / 5)));
    const cMaxZ = Math.max(0, Math.min(47, Math.floor((maxZ + 120) / 5)));

    for (let cx = cMinX; cx <= cMaxX; cx++) {
      const x0 = -120 + cx * 5, x1 = x0 + 5;
      for (let cz = cMinZ; cz <= cMaxZ; cz++) {
        const z0 = -120 + cz * 5, z1 = z0 + 5;
        const cellTris: [P2, P2, P2][] = [
          [[x0, z0], [x0, z1], [x1, z0]],
          [[x0, z1], [x1, z1], [x1, z0]]
        ];
        for (const ct of cellTris) {
          const clipped = clipPoly([p0, p1, p2], ct);
          const clean: P2[] = [];
          for (let k = 0; k < clipped.length; k++) {
            const pt = clipped[k], nxt = clipped[(k + 1) % clipped.length];
            if (Math.hypot(pt[0] - nxt[0], pt[1] - nxt[1]) > 1e-4) clean.push(pt);
          }
          if (clean.length < 3) continue;
          let area = 0;
          for (let k = 0; k < clean.length; k++) {
            const curr = clean[k], nxt = clean[(k + 1) % clean.length];
            area += curr[0] * nxt[1] - nxt[0] * curr[1];
          }
          if (Math.abs(area) * 0.5 < 1e-5) continue;
          const origCross = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0]);
          const ordered = (area >= 0) === (origCross >= 0) ? clean : clean.slice().reverse();
          for (let k = 1; k < ordered.length - 1; k++) {
            const triPts = [ordered[0], ordered[k], ordered[k + 1]];
            for (const pt of triPts) {
              outCoords.push(pt[0], getTerrainSurfaceHeight(pt[0], pt[1], noise) + 0.06, pt[1]);
            }
          }
        }
      }
    }
  }

  const res = new THREE.BufferGeometry();
  res.setAttribute('position', new THREE.Float32BufferAttribute(outCoords, 3));
  res.computeVertexNormals();
  return res;
}

/**
 * Builds a grounded continuous landscape with roads, road marks, peripheral foliage, and continuous paths.
 */
export function createEnvironment(seed: string = 'default-seed'): GroundedEnvironmentGroup {
  const rng = createPrng(seed);
  const noise = createPerlinLike2D(rng);

  const root = new THREE.Group() as GroundedEnvironmentGroup;
  root.name = 'GroundedEnvironment';

  let totalTriangles = 0;
  let totalDrawCalls = 0;

  const colorSage1 = new THREE.Color('#91a879');
  const colorSage2 = new THREE.Color('#9aae83');
  const colorSage3 = new THREE.Color('#b4bd94');
  const colorEarth = new THREE.Color('#9d9276');
  const colorStone = new THREE.Color('#c3bea7');
  const colorAsphalt = new THREE.Color('#7e8b7c');
  const colorTrunk = new THREE.Color('#635242');
  const colorFoliageA = new THREE.Color('#587243');
  const colorFoliageB = new THREE.Color('#789456');
  const colorRoadMark = new THREE.Color('#e0dfd5');

  // 1. Terrain Mesh with vertex colors and receiveShadow true
  const groundGeo = new THREE.PlaneGeometry(
    GROUND_SIZE,
    GROUND_SIZE,
    GROUND_SEGMENTS,
    GROUND_SEGMENTS
  );
  groundGeo.rotateX(-Math.PI / 2);

  const posAttr = groundGeo.attributes.position;
  if (posAttr) {
    const count = posAttr.count;
    const colors = new Float32Array(count * 3);
    const tempCol = new THREE.Color();

    for (let i = 0; i < count; i++) {
      const x = posAttr.getX(i);
      const z = posAttr.getZ(i);
      const h = getTerrainHeight(x, z, noise);
      posAttr.setY(i, h);

      const nCol = noise(x * 0.04 + 50.0, z * 0.04 + 50.0);
      if (nCol < -0.1) {
        tempCol.copy(colorSage1).lerp(colorEarth, Math.min(1, Math.abs(nCol + 0.1) * 2));
      } else if (nCol < 0.25) {
        tempCol.copy(colorSage2).lerp(colorSage3, nCol * 2);
      } else {
        tempCol.copy(colorSage3).lerp(colorSage1, (nCol - 0.25) * 2);
      }
      colors[i * 3] = tempCol.r;
      colors[i * 3 + 1] = tempCol.g;
      colors[i * 3 + 2] = tempCol.b;
    }
    groundGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    groundGeo.computeVertexNormals();
  }

  const groundMat = new THREE.MeshLambertMaterial({
    vertexColors: true,
    flatShading: true,
  });
  const groundMesh = new THREE.Mesh(groundGeo, groundMat);
  groundMesh.name = 'Terrain';
  groundMesh.receiveShadow = true;
  root.add(groundMesh);
  totalDrawCalls += 1;
  totalTriangles += (groundGeo.index ? groundGeo.index.count / 3 : (groundGeo.attributes.position?.count ?? 0) / 3);

  // 2. Roads (5 Horizontal at y=0.012, 5 Vertical at y=0.016)
  const hRoadGeo = new THREE.PlaneGeometry(ROAD_LENGTH, ROAD_WIDTH);
  hRoadGeo.rotateX(-Math.PI / 2);
  const vRoadGeo = new THREE.PlaneGeometry(ROAD_WIDTH, ROAD_LENGTH);
  vRoadGeo.rotateX(-Math.PI / 2);

  const roadMat = new THREE.MeshLambertMaterial({ color: colorAsphalt });
  const hRoadMesh = new THREE.InstancedMesh(hRoadGeo, roadMat, 5);
  const vRoadMesh = new THREE.InstancedMesh(vRoadGeo, roadMat, 5);
  hRoadMesh.name = 'RoadsHorizontal';
  vRoadMesh.name = 'RoadsVertical';
  hRoadMesh.receiveShadow = true;
  vRoadMesh.receiveShadow = true;

  const dummy = new THREE.Object3D();
  ROAD_COORDINATES.forEach((coord, idx) => {
    dummy.position.set(0, 0.012, coord);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    hRoadMesh.setMatrixAt(idx, dummy.matrix);
  });
  ROAD_COORDINATES.forEach((coord, idx) => {
    dummy.position.set(coord, 0.016, 0);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    vRoadMesh.setMatrixAt(idx, dummy.matrix);
  });

  hRoadMesh.instanceMatrix.needsUpdate = true;
  vRoadMesh.instanceMatrix.needsUpdate = true;
  root.add(hRoadMesh);
  root.add(vRoadMesh);
  totalDrawCalls += 2;
  totalTriangles += (2 * 5) + (2 * 5); // 2 tris per quad * 10 = 20 tris

  // 3. Road Markings (Dashed centerline planes at y=0.020, avoiding intersections)
  const dashGeo = new THREE.PlaneGeometry(1.2, 0.22);
  dashGeo.rotateX(-Math.PI / 2);
  const dashMat = new THREE.MeshBasicMaterial({ color: colorRoadMark });

  const dashPositions: Array<{ x: number; z: number; rotY: number }> = [];
  const halfLen = ROAD_LENGTH / 2;
  const halfWid = ROAD_WIDTH / 2;
  const dashStep = 2.6;

  // Generate dashes for 5 horizontal roads (parallel to X axis)
  for (const rz of ROAD_COORDINATES) {
    for (let x = -halfLen + 1.2; x <= halfLen - 1.2; x += dashStep) {
      // Check if dash falls within intersection with any vertical road
      let insideIntersection = false;
      for (const rx of ROAD_COORDINATES) {
        if (Math.abs(x - rx) < halfWid + 0.3) {
          insideIntersection = true;
          break;
        }
      }
      if (!insideIntersection) {
        dashPositions.push({ x, z: rz, rotY: 0 });
      }
    }
  }

  // Generate dashes for 5 vertical roads (parallel to Z axis)
  for (const rx of ROAD_COORDINATES) {
    for (let z = -halfLen + 1.2; z <= halfLen - 1.2; z += dashStep) {
      // Check if dash falls within intersection with any horizontal road
      let insideIntersection = false;
      for (const rz of ROAD_COORDINATES) {
        if (Math.abs(z - rz) < halfWid + 0.3) {
          insideIntersection = true;
          break;
        }
      }
      if (!insideIntersection) {
        dashPositions.push({ x: rx, z, rotY: Math.PI / 2 });
      }
    }
  }

  const markCount = Math.min(130, dashPositions.length);
  const roadMarkMesh = new THREE.InstancedMesh(dashGeo, dashMat, markCount);
  roadMarkMesh.name = 'RoadMarkings';

  for (let i = 0; i < markCount; i++) {
    const d = dashPositions[i]!;
    dummy.position.set(d.x, 0.02, d.z);
    dummy.rotation.set(0, d.rotY, 0);
    dummy.scale.set(1, 1, 1);
    dummy.updateMatrix();
    roadMarkMesh.setMatrixAt(i, dummy.matrix);
  }
  roadMarkMesh.instanceMatrix.needsUpdate = true;
  root.add(roadMarkMesh);
  totalDrawCalls += 1;
  totalTriangles += 2 * markCount;

  // 4. Continuous Peripheral Footpath Ribbons (Ring + Avenue exit ribbons, single merged strip geometry)
  const pathRibbonGeos: THREE.BufferGeometry[] = [];
  const pathMat = new THREE.MeshLambertMaterial({ color: colorStone, side: THREE.DoubleSide });

  // A. Outer continuous circular ribbon ring outside Chebyshev 34+
  const ringSegments = 300;
  const ringWidth = 1.8;
  const ringPositions = new Float32Array((ringSegments + 1) * 2 * 3);
  const ringIndices: number[] = [];

  for (let i = 0; i <= ringSegments; i++) {
    const angle = (i / ringSegments) * Math.PI * 2;
    const baseR = 48.0 + Math.sin(angle * 4) * 5.0 + Math.cos(angle * 2) * 4.0;
    const innerR = baseR - ringWidth / 2;
    const outerR = baseR + ringWidth / 2;

    const cosA = Math.cos(angle);
    const sinA = Math.sin(angle);

    const inX = cosA * innerR;
    const inZ = sinA * innerR;
    const inY = getTerrainSurfaceHeight(inX, inZ, noise) + 0.06;

    const outX = cosA * outerR;
    const outZ = sinA * outerR;
    const outY = getTerrainSurfaceHeight(outX, outZ, noise) + 0.06;

    const vIdx = i * 2;
    ringPositions[vIdx * 3] = inX;
    ringPositions[vIdx * 3 + 1] = inY;
    ringPositions[vIdx * 3 + 2] = inZ;

    ringPositions[(vIdx + 1) * 3] = outX;
    ringPositions[(vIdx + 1) * 3 + 1] = outY;
    ringPositions[(vIdx + 1) * 3 + 2] = outZ;

    if (i < ringSegments) {
      const a = vIdx;
      const b = vIdx + 1;
      const c = vIdx + 2;
      const d = vIdx + 3;
      ringIndices.push(a, b, c);
      ringIndices.push(b, d, c);
    }
  }

  const ringGeo = new THREE.BufferGeometry();
  ringGeo.setAttribute('position', new THREE.BufferAttribute(ringPositions, 3));
  ringGeo.setIndex(ringIndices);
  pathRibbonGeos.push(ringGeo);

  // B. Connecting Avenue Exit Ribbons (from avenue exits Chebyshev 34+ to ring, outside central city)
  const exitRibbonSegments = 45;
  const exitConfigs = [
    { startX: 34.0, startZ: 0, endX: 52.0, endZ: 0, nx: 0, nz: 1 },
    { startX: -34.0, startZ: 0, endX: -52.0, endZ: 0, nx: 0, nz: 1 },
  ];

  for (const cfg of exitConfigs) {
    const ribbonPos = new Float32Array((exitRibbonSegments + 1) * 2 * 3);
    const ribbonInd: number[] = [];
    const halfW = 1.0;

    for (let i = 0; i <= exitRibbonSegments; i++) {
      const t = i / exitRibbonSegments;
      const cx = THREE.MathUtils.lerp(cfg.startX, cfg.endX, t);
      const cz = THREE.MathUtils.lerp(cfg.startZ, cfg.endZ, t);

      const leftX = cx + cfg.nx * halfW;
      const leftZ = cz + cfg.nz * halfW;
      const leftY = getTerrainSurfaceHeight(leftX, leftZ, noise) + 0.06;

      const rightX = cx - cfg.nx * halfW;
      const rightZ = cz - cfg.nz * halfW;
      const rightY = getTerrainSurfaceHeight(rightX, rightZ, noise) + 0.06;

      const vIdx = i * 2;
      ribbonPos[vIdx * 3] = leftX;
      ribbonPos[vIdx * 3 + 1] = leftY;
      ribbonPos[vIdx * 3 + 2] = leftZ;

      ribbonPos[(vIdx + 1) * 3] = rightX;
      ribbonPos[(vIdx + 1) * 3 + 1] = rightY;
      ribbonPos[(vIdx + 1) * 3 + 2] = rightZ;

      if (i < exitRibbonSegments) {
        const a = vIdx;
        const b = vIdx + 1;
        const c = vIdx + 2;
        const d = vIdx + 3;
        ribbonInd.push(a, b, c);
        ribbonInd.push(b, d, c);
      }
    }

    const exitGeo = new THREE.BufferGeometry();
    exitGeo.setAttribute('position', new THREE.BufferAttribute(ribbonPos, 3));
    exitGeo.setIndex(ribbonInd);
    pathRibbonGeos.push(exitGeo);
  }

  const rawPathGeo = BufferGeometryUtils.mergeGeometries(pathRibbonGeos, false);
  const mergedPathGeo = rawPathGeo ? conformPathGeometry(rawPathGeo, noise) : null;
  rawPathGeo?.dispose();
  pathRibbonGeos.forEach((g) => g.dispose());
  if (mergedPathGeo) {
    mergedPathGeo.computeVertexNormals();
    const pathMesh = new THREE.Mesh(mergedPathGeo, pathMat);
    pathMesh.name = 'ContinuousFootpaths';
    root.add(pathMesh);
    totalDrawCalls += 1;
    totalTriangles += mergedPathGeo.index ? mergedPathGeo.index.count / 3 : (mergedPathGeo.attributes.position?.count ?? 0) / 3;
  }

  // 5. Instanced Clustered Natural Trees (9 groves outside 40+, jitter 8-12, all trees max(absx, absz) >= 34)
  const numTrees = 75;
  // CylinderGeometry with openEnded=false generates 3 groups if not merged; unified into single group BufferGeometry
  const rawTrunkGeo = new THREE.CylinderGeometry(0.2, 0.38, 2.8, 6, 1, false);
  rawTrunkGeo.translate(0, 1.4, 0);
  rawTrunkGeo.clearGroups(); // Single draw call
  const trunkGeo = rawTrunkGeo;

  const trunkMat = new THREE.MeshLambertMaterial({ color: colorTrunk, flatShading: true });
  const trunkMesh = new THREE.InstancedMesh(trunkGeo, trunkMat, numTrees);
  trunkMesh.name = 'TreeTrunks';

  const foliageGeo = new THREE.IcosahedronGeometry(1.35, 0);
  foliageGeo.clearGroups();
  const foliageMat = new THREE.MeshLambertMaterial({ color: '#ffffff', flatShading: true });
  const totalCrowns = numTrees * 3;
  const foliageMesh = new THREE.InstancedMesh(foliageGeo, foliageMat, totalCrowns);
  foliageMesh.name = 'TreeFoliageCrowns';

  // Seed ~9 natural grove centers outside 40+ with tree jitter 8-12
  const groveCenters: Array<{ x: number; z: number }> = [];
  const numGroves = 9;
  for (let g = 0; g < numGroves; g++) {
    const gAngle = (g / numGroves) * Math.PI * 2 + (rng() - 0.5) * 0.4;
    const gDist = 50.0 + rng() * 32.0;
    groveCenters.push({
      x: Math.cos(gAngle) * gDist,
      z: Math.sin(gAngle) * gDist,
    });
  }

  const treeCoords: Array<{ x: number; z: number; scale: number }> = [];
  let groveIdx = 0;
  while (treeCoords.length < numTrees) {
    const grove = groveCenters[groveIdx % numGroves]!;
    groveIdx++;
    const jAngle = rng() * Math.PI * 2;
    const jDist = 1.5 + rng() * 10.5; // jitter 8-12 span
    const tx = grove.x + Math.cos(jAngle) * jDist;
    const tz = grove.z + Math.sin(jAngle) * jDist;
    const chebyshev = Math.max(Math.abs(tx), Math.abs(tz));

    if (chebyshev >= 34.0 && Math.abs(tx) < 110 && Math.abs(tz) < 110) {
      treeCoords.push({
        x: tx,
        z: tz,
        scale: 0.8 + rng() * 0.45,
      });
    }
  }

  let crownIdx = 0;
  for (let i = 0; i < treeCoords.length; i++) {
    const tc = treeCoords[i]!;
    const y = getTerrainSurfaceHeight(tc.x, tc.z, noise);

    dummy.position.set(tc.x, y, tc.z);
    dummy.rotation.set(0, rng() * Math.PI * 2, 0);
    dummy.scale.set(tc.scale, tc.scale, tc.scale);
    dummy.updateMatrix();
    trunkMesh.setMatrixAt(i, dummy.matrix);

    const crownOffsets = [
      { ox: 0, oy: 2.7 * tc.scale, oz: 0, s: 1.15 * tc.scale },
      { ox: 0.45 * tc.scale, oy: 2.2 * tc.scale, oz: 0.3 * tc.scale, s: 0.85 * tc.scale },
      { ox: -0.4 * tc.scale, oy: 2.3 * tc.scale, oz: -0.35 * tc.scale, s: 0.8 * tc.scale },
    ];

    for (const co of crownOffsets) {
      dummy.position.set(tc.x + co.ox, y + co.oy, tc.z + co.oz);
      dummy.rotation.set(rng() * 0.3, rng() * Math.PI * 2, rng() * 0.3);
      dummy.scale.set(co.s, co.s * (0.85 + rng() * 0.3), co.s);
      dummy.updateMatrix();
      foliageMesh.setMatrixAt(crownIdx, dummy.matrix);
      foliageMesh.setColorAt(crownIdx, rng() > 0.4 ? colorFoliageA : colorFoliageB);
      crownIdx++;
    }
  }

  trunkMesh.instanceMatrix.needsUpdate = true;
  foliageMesh.instanceMatrix.needsUpdate = true;
  if (foliageMesh.instanceColor) {
    foliageMesh.instanceColor.needsUpdate = true;
  }
  root.add(trunkMesh);
  root.add(foliageMesh);
  totalDrawCalls += 2;
  const trunkTris = (trunkGeo.index ? trunkGeo.index.count / 3 : (trunkGeo.attributes.position?.count ?? 0) / 3) * numTrees;
  const folTris = (foliageGeo.index ? foliageGeo.index.count / 3 : (foliageGeo.attributes.position?.count ?? 0) / 3) * totalCrowns;
  totalTriangles += trunkTris + folTris;

  // 6. Instanced Meadow Grass Patches (Strictly outside square 33.0 Chebyshev to keep quad edges outside 30.0)
  const grassCount = 120;
  const grassTriGeo = new THREE.BufferGeometry();
  const grassVerts = new Float32Array([
    -0.25, 0, 0,
     0.25, 0, 0,
     0.0, 0.75, 0,
  ]);
  grassTriGeo.setAttribute('position', new THREE.BufferAttribute(grassVerts, 3));
  grassTriGeo.computeVertexNormals();

  const grassMat = new THREE.MeshBasicMaterial({
    color: colorSage3,
    side: THREE.DoubleSide,
  });
  const grassMesh = new THREE.InstancedMesh(grassTriGeo, grassMat, grassCount);
  grassMesh.name = 'MeadowGrassPatches';

  const grassCoords: Array<{ x: number; z: number }> = [];
  while (grassCoords.length < grassCount) {
    const gx = (rng() - 0.5) * 220;
    const gz = (rng() - 0.5) * 220;
    const chebyshev = Math.max(Math.abs(gx), Math.abs(gz));
    if (chebyshev >= 33.0) {
      grassCoords.push({ x: gx, z: gz });
    }
  }

  for (let i = 0; i < grassCount; i++) {
    const g = grassCoords[i]!;
    const gy = getTerrainSurfaceHeight(g.x, g.z, noise);
    dummy.position.set(g.x, gy, g.z);
    dummy.rotation.set(0, rng() * Math.PI * 2, 0);
    dummy.scale.set(0.8 + rng() * 0.6, 0.8 + rng() * 0.8, 1);
    dummy.updateMatrix();
    grassMesh.setMatrixAt(i, dummy.matrix);
  }
  grassMesh.instanceMatrix.needsUpdate = true;
  root.add(grassMesh);
  totalDrawCalls += 1;
  totalTriangles += 1 * grassCount;

  const stats: EnvironmentalStats = {
    drawCalls: totalDrawCalls,
    triangles: Math.round(totalTriangles),
    cosmeticOnly: true,
  };

  root.userData = {
    environmentalStats: stats,
    seed,
    bounds: {
      size: GROUND_SIZE,
      citySquareHalf: CITY_SQUARE_HALF,
      terrainStartSquare: TERRAIN_OUTER_SQUARE,
    },
  };

  return root;
}
