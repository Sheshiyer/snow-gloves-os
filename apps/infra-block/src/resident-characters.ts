import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import type { BuildingState, GameState, CrewControlState } from './contracts';
import { navigateCrew, safeCrewHome, type CrewPoint } from './crew-navigation';
import type { ResidentDefinition, ResidentPresence, ResidentSlug } from './residents';

export interface ResidentCrew {
  readonly group: THREE.Group;
  readonly pickTargets: THREE.Object3D[];
  setPresence(presence: readonly ResidentPresence[]): void;
  controlResident(slug: string | null): void;
  moveResident(input: CrewPoint, forward: CrewPoint, dt: number): CrewControlState;
  controlState(): CrewControlState;
  update(dt: number, mode: GameState['mode']): void;
  dispose(): void;
}

const ROAD_COORDS = [-20.8, -10.4, 0, 10.4, 20.8] as const;
const SPEED = 1.5;
const MAX_DT = 0.1;
const PLATFORM_BOUND = 26.3;

interface ResidentVisuals {
  slug: ResidentSlug;
  definition: ResidentDefinition;
  rootGroup: THREE.Group;
  actorGroup: THREE.Group;
  stationGroup: THREE.Group;
  leftArm: THREE.Object3D;
  rightArm: THREE.Object3D;
  leftLeg: THREE.Object3D;
  rightLeg: THREE.Object3D;
  gateMesh: THREE.Mesh;
  plaqueTexture: THREE.CanvasTexture;
  plaqueMaterial: THREE.MeshBasicMaterial;
  homePos: THREE.Vector3;
  stationPos: THREE.Vector3;
  waypoints: THREE.Vector3[];
  currentLeg: number;
  legProgress: number;
  walkCycle: number;
  presence: ResidentPresence;
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}

function findNearestRoadCoord(val: number): number {
  let nearest: number = ROAD_COORDS[0];
  let minDiff = Math.abs(val - nearest);
  for (let i = 1; i < ROAD_COORDS.length; i++) {
    const diff = Math.abs(val - ROAD_COORDS[i]);
    if (diff < minDiff) {
      minDiff = diff;
      nearest = ROAD_COORDS[i];
    }
  }
  return nearest;
}

function sanitizeText(str: string, maxLen = 32): string {
  return str.replace(/[^\w\s-.:/]/g, '').slice(0, maxLen);
}

function createPlaqueCanvas(
  name: string,
  role: string,
  presence: ResidentPresence
): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;

  ctx.fillStyle = '#F5EFEB';
  ctx.fillRect(0, 0, 512, 128);

  ctx.strokeStyle = '#2A2521';
  ctx.lineWidth = 6;
  ctx.strokeRect(3, 3, 506, 122);

  ctx.fillStyle = '#1D1A17';
  ctx.font = 'bold 36px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(sanitizeText(name, 20), 20, 48);

  ctx.font = 'normal 24px sans-serif';
  ctx.fillStyle = '#5A524C';
  ctx.fillText(sanitizeText(role, 24), 20, 84);

  const isDemo = presence.evidence === 'demo';
  const prefix = isDemo ? '[DEMO] ' : '';
  const rawStatus = presence.label || presence.state;
  const statusStr = prefix + sanitizeText(rawStatus, 18);

  ctx.textAlign = 'right';
  ctx.font = 'bold 22px sans-serif';
  if (presence.state === 'active') ctx.fillStyle = '#1B6E3F';
  else if (presence.state === 'held') ctx.fillStyle = '#8B2B2B';
  else ctx.fillStyle = '#6E6259';
  ctx.fillText(statusStr.toUpperCase(), 492, 108);

  return canvas;
}

export function createResidentCrew(
  definitions: readonly ResidentDefinition[],
  buildings: readonly BuildingState[],
  reducedMotion: boolean
): ResidentCrew {
  const rootGroup = new THREE.Group();
  rootGroup.name = 'ResidentCrewRoot';

  const pickTargets: THREE.Object3D[] = [];
  const allocatedGeometries = new Set<THREE.BufferGeometry>();
  const allocatedMaterials = new Set<THREE.Material>();
  const allocatedTextures = new Set<THREE.Texture>();

  const trackMat = <T extends THREE.Material>(m: T): T => {
    allocatedMaterials.add(m);
    return m;
  };
  const trackGeo = <T extends THREE.BufferGeometry>(g: T): T => {
    allocatedGeometries.add(g);
    return g;
  };
  const trackTex = <T extends THREE.Texture>(t: T): T => {
    allocatedTextures.add(t);
    return t;
  };

  const buildingFronts = new Map<string, THREE.Vector3>();
  for (const b of buildings) {
    const fz = clamp(b.z + b.depth * 0.5 + 1.7, -24, 24);
    const fx = clamp(b.x + b.width * 0.5 + 1.7, -24, 24);
    buildingFronts.set(b.id, new THREE.Vector3(fx, 0, fz));
  }

  const residents: ResidentVisuals[] = [];

  // Shared low-poly humanoid geometry library
  const sharedHeadGeo = trackGeo(new THREE.SphereGeometry(0.38, 12, 8));
  const sharedTorsoGeo = trackGeo(new THREE.CylinderGeometry(0.38, 0.44, 1.0, 12));
  const sharedLimbGeo = trackGeo(new THREE.CylinderGeometry(0.12, 0.14, 0.75, 8));
  const sharedFootGeo = trackGeo(new THREE.SphereGeometry(0.18, 8, 6));
  const sharedHandGeo = trackGeo(new THREE.SphereGeometry(0.11, 8, 6));
  const sharedEyeGeo = trackGeo(new THREE.SphereGeometry(0.045, 8, 6));
  const sharedBrowGeo = trackGeo(new THREE.BoxGeometry(0.12, 0.03, 0.04));


  for (const def of definitions) {
    const bPos = buildingFronts.get(def.nodeId);
    if (!bPos) continue;
    const stationPos = bPos.clone();
    const homePos = new THREE.Vector3(bPos.x - 0.8, 0, bPos.z + 0.3);

    const residentRoot = new THREE.Group();
    residentRoot.name = `Resident_${def.slug}`;
    residentRoot.userData.residentSlug = def.slug;

    const actorGroup = new THREE.Group();
    actorGroup.name = `Actor_${def.slug}`;
    actorGroup.userData.residentSlug = def.slug;
    actorGroup.position.copy(homePos);

    const stationGroup = new THREE.Group();
    stationGroup.name = `Station_${def.slug}`;
    stationGroup.userData.residentSlug = def.slug;
    stationGroup.position.copy(stationPos);

    // Common materials
    const mainColor = new THREE.Color(def.color);
    const accentColor = new THREE.Color(def.accent);
    const skinMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xffe0c8, roughness: 0.8 }));
    const darkInkMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x1d1a17, roughness: 0.7 }));
    const suitMat = trackMat(new THREE.MeshStandardMaterial({ color: mainColor, roughness: 0.85 }));
    const accentMat = trackMat(new THREE.MeshStandardMaterial({ color: accentColor, roughness: 0.75 }));
    const rubberMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.9 }));
    const woodPlinthMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xd6c4b2, roughness: 0.9 }));
    const metalMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x9ba2a8, roughness: 0.4, metalness: 0.6 }));

    // Joint groups for walking
    const leftArm = new THREE.Group();
    const rightArm = new THREE.Group();
    const leftLeg = new THREE.Group();
    const rightLeg = new THREE.Group();

    // Setup base rig
    leftLeg.position.set(-0.35, 0.9, 0);
    rightLeg.position.set(0.35, 0.9, 0);
    leftArm.position.set(-0.65, 2.1, 0);
    rightArm.position.set(0.65, 2.1, 0);

    const lLegMesh = new THREE.Mesh(sharedLimbGeo, suitMat);
    lLegMesh.position.y = -0.35;
    const lFootMesh = new THREE.Mesh(sharedFootGeo, rubberMat);
    lFootMesh.scale.set(0.9, 0.6, 1.4);
    lFootMesh.position.set(0, -0.73, 0.08);
    leftLeg.add(lLegMesh, lFootMesh);

    const rLegMesh = new THREE.Mesh(sharedLimbGeo, suitMat);
    rLegMesh.position.y = -0.35;
    const rFootMesh = new THREE.Mesh(sharedFootGeo, rubberMat);
    rFootMesh.scale.set(0.9, 0.6, 1.4);
    rFootMesh.position.set(0, -0.73, 0.08);
    rightLeg.add(rLegMesh, rFootMesh);

    const lArmMesh = new THREE.Mesh(sharedLimbGeo, suitMat);
    lArmMesh.position.y = -0.35;
    const lHandMesh = new THREE.Mesh(sharedHandGeo, skinMat);
    lHandMesh.position.y = -0.72;
    leftArm.add(lArmMesh, lHandMesh);

    const rArmMesh = new THREE.Mesh(sharedLimbGeo, suitMat);
    rArmMesh.position.y = -0.35;
    const rHandMesh = new THREE.Mesh(sharedHandGeo, skinMat);
    rHandMesh.position.y = -0.72;
    rightArm.add(rArmMesh, rHandMesh);

    actorGroup.add(leftLeg, rightLeg, leftArm, rightArm);

    // Build specific silhouettes & props
    let headCenterY = 2.6;
    let showStandardEyes = true;

    if (def.slug === 'ceo') {
      headCenterY = 2.65;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.35, 1.4, 0.95);
      torso.position.y = 1.6;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.95, 1.05, 0.95);
      head.position.y = headCenterY;

      const hatGeo = trackGeo(new THREE.CylinderGeometry(0.38, 0.44, 0.32, 12));
      const hat = new THREE.Mesh(hatGeo, accentMat);
      hat.position.y = 3.08;

      const brimGeo = trackGeo(new THREE.CylinderGeometry(0.62, 0.62, 0.05, 12));
      const brim = new THREE.Mesh(brimGeo, accentMat);
      brim.position.y = 2.92;

      const compassGeo = trackGeo(new THREE.CylinderGeometry(0.18, 0.18, 0.06, 10));
      const compass = new THREE.Mesh(compassGeo, metalMat);
      compass.rotation.x = Math.PI / 2;
      compass.position.set(0, 1.9, 0.38);

      const mapGeo = trackGeo(new THREE.BoxGeometry(0.18, 0.45, 0.18));
      const mapMesh = new THREE.Mesh(mapGeo, trackMat(new THREE.MeshStandardMaterial({ color: 0xfff9e6 })));
      mapMesh.position.set(0, -0.4, 0.2);
      rightArm.add(mapMesh);

      actorGroup.add(torso, head, hat, brim, compass);
    } else if (def.slug === 'cto') {
      headCenterY = 2.35;
      showStandardEyes = false;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.5, 1.15, 1.15);
      torso.position.y = 1.45;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(1.05, 0.9, 0.95);
      head.position.y = headCenterY;

      const visorGeo = trackGeo(new THREE.BoxGeometry(0.55, 0.16, 0.22));
      const visor = new THREE.Mesh(visorGeo, accentMat);
      visor.position.set(0, 2.38, 0.32);

      const wrenchGeo = trackGeo(new THREE.BoxGeometry(0.1, 0.8, 0.18));
      const wrench = new THREE.Mesh(wrenchGeo, darkInkMat);
      wrench.position.set(0, -0.4, 0.2);
      rightArm.add(wrench);

      actorGroup.add(torso, head, visor);
    } else if (def.slug === 'chief-of-staff') {
      headCenterY = 2.5;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.15, 1.3, 0.85);
      torso.position.y = 1.55;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.9, 1.0, 0.9);
      head.position.y = headCenterY;

      const cupGeo = trackGeo(new THREE.CylinderGeometry(0.14, 0.14, 0.12, 10));
      const lCup = new THREE.Mesh(cupGeo, accentMat);
      lCup.rotation.z = Math.PI / 2;
      lCup.position.set(-0.4, 2.5, 0);
      const rCup = lCup.clone();
      rCup.position.set(0.4, 2.5, 0);

      const clipGeo = trackGeo(new THREE.BoxGeometry(0.35, 0.55, 0.05));
      const clipboard = new THREE.Mesh(clipGeo, accentMat);
      clipboard.position.set(0, -0.4, 0.2);
      leftArm.add(clipboard);

      actorGroup.add(torso, head, lCup, rCup);
    } else if (def.slug === 'librarian') {
      headCenterY = 2.55;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.35, 1.3, 1.05);
      torso.position.y = 1.55;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.95, 1.02, 0.95);
      head.position.y = headCenterY;

      const glassesGeo = trackGeo(new THREE.TorusGeometry(0.1, 0.025, 6, 12));
      const lGlass = new THREE.Mesh(glassesGeo, darkInkMat);
      lGlass.position.set(-0.15, 2.58, 0.34);
      const rGlass = lGlass.clone();
      rGlass.position.set(0.15, 2.58, 0.34);

      const bookGeo = trackGeo(new THREE.BoxGeometry(0.32, 0.45, 0.4));
      const books = new THREE.Mesh(bookGeo, accentMat);
      books.position.set(0, -0.35, 0.25);
      leftArm.add(books);

      actorGroup.add(torso, head, lGlass, rGlass);
    } else if (def.slug === 'interpreter') {
      headCenterY = 2.6;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.15, 1.4, 0.9);
      torso.position.y = 1.6;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.92, 1.02, 0.92);
      head.position.y = headCenterY;

      const prismHatGeo = trackGeo(new THREE.ConeGeometry(0.4, 0.55, 4));
      const prismHat = new THREE.Mesh(prismHatGeo, accentMat);
      prismHat.position.y = 3.15;

      const lensGeo = trackGeo(new THREE.CylinderGeometry(0.18, 0.18, 0.04, 12));
      const lens = new THREE.Mesh(lensGeo, trackMat(new THREE.MeshStandardMaterial({ color: 0xffaa00, transparent: true, opacity: 0.7 })));
      lens.rotation.x = Math.PI / 2;
      lens.position.set(0, -0.3, 0.25);
      rightArm.add(lens);

      actorGroup.add(torso, head, prismHat);
    } else if (def.slug === 'dispatcher') {
      headCenterY = 2.55;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.2, 1.35, 0.9);
      torso.position.y = 1.55;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.92, 1.0, 0.92);
      head.position.y = headCenterY;

      const capGeo = trackGeo(new THREE.CylinderGeometry(0.38, 0.42, 0.18, 12));
      const cap = new THREE.Mesh(capGeo, suitMat);
      cap.position.y = 2.95;

      const brimGeo = trackGeo(new THREE.BoxGeometry(0.48, 0.04, 0.25));
      const brim = new THREE.Mesh(brimGeo, darkInkMat);
      brim.position.set(0, 2.88, 0.3);

      const bagGeo = trackGeo(new THREE.BoxGeometry(0.28, 0.4, 0.48));
      const bag = new THREE.Mesh(bagGeo, accentMat);
      bag.position.set(-0.55, 1.4, 0);

      actorGroup.add(torso, head, cap, brim, bag);
    } else {
      // Sentinel
      headCenterY = 2.6;
      const torso = new THREE.Mesh(sharedTorsoGeo, suitMat);
      torso.scale.set(1.45, 1.4, 1.05);
      torso.position.y = 1.6;

      const head = new THREE.Mesh(sharedHeadGeo, skinMat);
      head.scale.set(0.95, 1.08, 0.95);
      head.position.y = headCenterY;

      const helmGeo = trackGeo(new THREE.CylinderGeometry(0.38, 0.42, 0.4, 12));
      const helm = new THREE.Mesh(helmGeo, trackMat(new THREE.MeshStandardMaterial({ color: 0xedebe4 })));
      helm.position.y = 2.95;

      const shieldGeo = trackGeo(new THREE.BoxGeometry(0.55, 1.0, 0.08));
      const shield = new THREE.Mesh(shieldGeo, metalMat);
      shield.position.set(0, -0.2, 0.2);
      leftArm.add(shield);

      const lanternGeo = trackGeo(new THREE.BoxGeometry(0.2, 0.3, 0.2));
      const lanternMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xffe28a, emissive: 0xffb700, emissiveIntensity: 0.6 }));
      const lantern = new THREE.Mesh(lanternGeo, lanternMat);
      lantern.position.set(0, -0.4, 0.2);
      rightArm.add(lantern);

      actorGroup.add(torso, head, helm);
    }

    // Friendly face details
    if (showStandardEyes) {
      const lEye = new THREE.Mesh(sharedEyeGeo, darkInkMat);
      lEye.position.set(-0.14, headCenterY + 0.02, 0.34);
      const rEye = lEye.clone();
      rEye.position.set(0.14, headCenterY + 0.02, 0.34);

      const lBrow = new THREE.Mesh(sharedBrowGeo, darkInkMat);
      lBrow.position.set(-0.14, headCenterY + 0.12, 0.34);
      const rBrow = lBrow.clone();
      rBrow.position.set(0.14, headCenterY + 0.12, 0.34);
      actorGroup.add(lEye, rEye, lBrow, rBrow);
    }
    // Build Station Plinth
    const plinthGeo = trackGeo(new RoundedBoxGeometry(4.0, 0.3, 2.7, 2, 0.1));
    const plinth = new THREE.Mesh(plinthGeo, woodPlinthMat);
    plinth.position.y = 0.15;
    stationGroup.add(plinth);

    // Stepping stones to nearest road
    const stoneGeo = trackGeo(new THREE.BoxGeometry(0.8, 0.06, 0.6));
    const stoneMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x99948d, roughness: 0.9 }));
    const stone1 = new THREE.Mesh(stoneGeo, stoneMat);
    stone1.position.set(0, 0.03, 1.7);
    const stone2 = new THREE.Mesh(stoneGeo, stoneMat);
    stone2.position.set(0, 0.03, 2.4);
    stationGroup.add(stone1, stone2);

    // Station unique theme desk/prop
    const deskGeo = trackGeo(new THREE.BoxGeometry(1.6, 0.9, 0.8));
    const desk = new THREE.Mesh(deskGeo, accentMat);
    desk.position.set(0.8, 0.6, -0.3);
    stationGroup.add(desk);
const put = (mesh: THREE.Mesh | THREE.Group, parent: THREE.Object3D, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0) => {
  mesh.position.set(x, y, z);
  mesh.rotation.set(rx, ry, rz);
  parent.add(mesh);
  return mesh;
};

const stationMat = trackMat(new THREE.MeshStandardMaterial({ color: def.color, roughness: 0.85, metalness: 0.05 }));
const creamMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xfff6e5, roughness: 0.55 }));
const woodMat = trackMat(new THREE.MeshStandardMaterial({ color: 0x8a5229, roughness: 0.7 }));
const goldMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xf5b041, roughness: 0.8, metalness: 0.1 }));
const flagRedMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xe74c3c, roughness: 0.4 }));

// 3 Stepping stone walkway tiles in front of station desk
for (let i = 0; i < 3; i++) {
  const tile = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.55, 0.04, 0.4, 2, 0.02)), i % 2 === 0 ? creamMat : stationMat);
  put(tile, stationGroup, -0.6 + i * 0.6, 0.02, 1.15, 0, (i - 1) * 0.08, 0);
}

// Role specific workspace installations
const roleSlug = def.slug;
if (roleSlug === 'ceo') {
  const boardFrame = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.6, 1.1, 0.08, 2, 0.02)), woodMat);
  put(boardFrame, stationGroup, 0.85, 1.25, -0.45, -0.15, 0, 0);
  const mapSurface = new THREE.Mesh(trackGeo(new THREE.PlaneGeometry(1.45, 0.95)), creamMat);
  put(mapSurface, boardFrame, 0, 0, 0.045);
  const compassRing = new THREE.Mesh(trackGeo(new THREE.TorusGeometry(0.18, 0.025, 8, 24)), goldMat);
  put(compassRing, boardFrame, 0, 0.62, 0);
  const compassNeedle = new THREE.Mesh(trackGeo(new THREE.ConeGeometry(0.04, 0.22, 4)), flagRedMat);
  put(compassNeedle, boardFrame, 0, 0.62, 0.015, 0, 0, 0.78);
} else if (roleSlug === 'cto') {
  const pegBoard = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.5, 1.2, 0.06, 2, 0.015)), creamMat);
  put(pegBoard, stationGroup, 0.8, 1.3, -0.5, 0, -0.05, 0);
  const toolShelf = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.4, 0.08, 0.25, 2, 0.01)), stationMat);
  put(toolShelf, pegBoard, 0, -0.4, 0.12);
  const wrenchHandle = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.08, 0.45, 0.04, 2, 0.01)), metalMat);
  put(wrenchHandle, pegBoard, -0.4, 0.15, 0.05, 0, 0, -0.4);
  const wrenchUJaw = new THREE.Mesh(trackGeo(new THREE.TorusGeometry(0.09, 0.035, 6, 16, Math.PI * 1.4)), metalMat);
  put(wrenchUJaw, wrenchHandle, 0, 0.24, 0, 0, 0, 0.8);
  const toolPouch = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.18, 0.16, 0.1, 2, 0.02)), woodMat);
  put(toolPouch, actorGroup, 0.26, 0.7, 0, 0, 0, 0.2);
} else if (roleSlug === 'chief-of-staff') {
  const routeBoard = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.4, 1.0, 0.06, 2, 0.02)), darkInkMat);
  put(routeBoard, stationGroup, 0.75, 1.25, -0.45, -0.1, -0.1, 0);
  for (let n = 0; n < 4; n++) {
    const nodeDot = new THREE.Mesh(trackGeo(new THREE.SphereGeometry(0.055, 10, 10)), stationMat);
    put(nodeDot, routeBoard, -0.45 + (n % 2) * 0.9, -0.25 + Math.floor(n / 2) * 0.5, 0.04);
  }
  const antennaPole = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.018, 0.025, 0.75, 8)), metalMat);
  put(antennaPole, stationGroup, 1.5, 1.35, -0.45);
  const antennaDish = new THREE.Mesh(trackGeo(new THREE.ConeGeometry(0.16, 0.1, 16, 1, true)), goldMat);
  put(antennaDish, antennaPole, 0, 0.38, 0, Math.PI * 0.85, 0, 0);
  const headsetBand = new THREE.Mesh(trackGeo(new THREE.TorusGeometry(0.24, 0.02, 6, 16, Math.PI)), metalMat);
  put(headsetBand, actorGroup, 0, 2.64, 0, Math.PI, 0, 0);
} else if (roleSlug === 'librarian') {
  const bookCase = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.5, 1.4, 0.45, 2, 0.03)), woodMat);
  put(bookCase, stationGroup, 0.85, 1.15, -0.45);
  const bookMat1 = stationMat;
  const bookMat2 = trackMat(new THREE.MeshStandardMaterial({ color: 0x9b59b6, roughness: 0.4 }));
  const bookMat3 = flagRedMat;
  for (let b = 0; b < 4; b++) {
    const book = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.12, 0.45, 0.32, 2, 0.01)), [bookMat1, bookMat2, bookMat3][b % 3]);
    put(book, bookCase, -0.5 + b * 0.16, 0.18, 0.04, 0, 0, (b === 3 ? -0.25 : 0));
    const pages = new THREE.Mesh(trackGeo(new THREE.BoxGeometry(0.09, 0.41, 0.28)), creamMat);
    put(pages, book, 0, 0, 0.02);
  }
  const deskStack = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.35, 0.25, 0.45, 2, 0.02)), creamMat);
  put(deskStack, stationGroup, 0.2, 0.82, -0.1);
} else if (roleSlug === 'interpreter') {
  const prismStand = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.04, 0.12, 0.6, 12)), woodMat);
  put(prismStand, stationGroup, 0.8, 1.05, -0.3);
  const multiPrism = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.22, 0.22, 0.4, 3)), trackMat(new THREE.MeshStandardMaterial({ color: 0x00d2d3, roughness: 0.7, metalness: 0.1, transparent: true, opacity: 0.85 })));
  put(multiPrism, prismStand, 0, 0.36, 0, 0.3, 0.4, 0.6);
  const prismRing = new THREE.Mesh(trackGeo(new THREE.TorusGeometry(0.25, 0.025, 8, 20)), goldMat);
  put(prismRing, prismStand, 0, 0.36, 0);
  const magLens = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.1, 0.1, 0.02, 16)), creamMat);
  const magStick = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.015, 0.015, 0.22, 8)), woodMat);
  put(magStick, magLens, 0, -0.16, 0);
  put(magLens, rightArm, 0, -0.25, 0.12, 0.7, 0, 0);
} else if (roleSlug === 'dispatcher') {
  const mailBox = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.48, 0.55, 0.7, 4, 0.08)), darkInkMat);
  put(mailBox, stationGroup, 0.95, 1.05, -0.35, 0, -0.3, 0);
  const mailSlot = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.28, 0.05, 0.02, 2, 0.01)), creamMat);
  put(mailSlot, mailBox, 0, 0.08, 0.355);
  const mailFlag = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.04, 0.24, 0.12, 2, 0.01)), flagRedMat);
  put(mailFlag, mailBox, 0.26, 0.12, -0.1, 0.3, 0, 0);
  const handheldEnvelope = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.3, 0.2, 0.04, 2, 0.01)), creamMat);
  const waxSeal = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.035, 0.035, 0.02, 12)), flagRedMat);
  put(waxSeal, handheldEnvelope, 0, 0, 0.025, Math.PI / 2, 0, 0);
  put(handheldEnvelope, leftArm, 0, -0.22, 0.14, 0.6, 0.3, 0);
} else if (roleSlug === 'sentinel') {
  const postPole = new THREE.Mesh(trackGeo(new THREE.CylinderGeometry(0.06, 0.08, 1.6, 12)), woodMat);
  put(postPole, stationGroup, 1.1, 1.1, -0.35);
  const lanternCap = new THREE.Mesh(trackGeo(new THREE.ConeGeometry(0.22, 0.14, 6)), goldMat);
  put(lanternCap, postPole, 0, 0.88, 0);
  const lanternGlass = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.22, 0.28, 0.22, 2, 0.02)), stationMat);
  put(lanternGlass, postPole, 0, 0.72, 0);
  const gateArm = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(1.4, 0.1, 0.06, 2, 0.01)), creamMat);
  put(gateArm, stationGroup, 0.45, 0.88, -0.35, 0, 0, 0.15);
  for (let s = 0; s < 3; s++) {
    const stripe = new THREE.Mesh(trackGeo(new RoundedBoxGeometry(0.12, 0.105, 0.065, 2, 0.01)), flagRedMat);
    put(stripe, gateArm, -0.4 + s * 0.35, 0, 0);
  }
}

    // Physical Gate Mesh (shown on held)
    const gateBarGeo = trackGeo(new THREE.CylinderGeometry(0.06, 0.06, 2.2, 8));
    const gateBarMat = trackMat(new THREE.MeshStandardMaterial({ color: 0xb53c3c, roughness: 0.5 }));
    const gateMesh = new THREE.Mesh(gateBarGeo, gateBarMat);
    gateMesh.rotation.z = Math.PI / 2;
    gateMesh.position.set(0, 1.1, 1.3);
    gateMesh.visible = false;
    stationGroup.add(gateMesh);

    // Plaque with CanvasTexture
    const initialPresence: ResidentPresence = {
      slug: def.slug,
      state: 'unknown',
      evidence: 'unobserved',
      label: 'Unknown',
      reason: 'Presence has not been observed',
      recordId: null,
      observedAt: null,
    };
    const plaqueCanvas = createPlaqueCanvas(def.slug.toUpperCase(), def.station, initialPresence);
    const plaqueTex = trackTex(new THREE.CanvasTexture(plaqueCanvas));
    plaqueTex.colorSpace = THREE.SRGBColorSpace;
    plaqueTex.anisotropy = 2;
    const plaqueMat = trackMat(new THREE.MeshBasicMaterial({ map: plaqueTex }));
    const plaqueGeo = trackGeo(new THREE.PlaneGeometry(3.7, 0.85));
    const plaqueMesh = new THREE.Mesh(plaqueGeo, plaqueMat);
    plaqueMesh.position.set(0, 0.8, 1.36);
    stationGroup.add(plaqueMesh);

    const actorBounds = new THREE.Box3().setFromObject(actorGroup);
    const actorHeight = actorBounds.getSize(new THREE.Vector3()).y;
    if (actorHeight > 0) actorGroup.scale.setScalar(4.2 / actorHeight);

    // Shadow flags
    actorGroup.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });
    stationGroup.traverse((obj) => {
      if ((obj as THREE.Mesh).isMesh) {
        obj.castShadow = true;
        obj.receiveShadow = true;
      }
    });

    residentRoot.add(stationGroup);
    residentRoot.add(actorGroup);
    rootGroup.add(residentRoot);

    pickTargets.push(actorGroup, stationGroup);

    // Construct deterministic Manhattan route waypoints
    const waypoints: THREE.Vector3[] = [homePos.clone()];
    const routeNodes = def.route.length > 0 ? def.route : [def.nodeId];
    for (const rNode of routeNodes) {
      const targetB = rNode === def.nodeId ? homePos : buildingFronts.get(rNode);
      if (!targetB) continue;
      const startX = waypoints.length > 0 ? waypoints[waypoints.length - 1].x : homePos.x;
      const startZ = waypoints.length > 0 ? waypoints[waypoints.length - 1].z : homePos.z;

      const roadZ = findNearestRoadCoord(startZ);
      const roadX = findNearestRoadCoord(startX);
      const destRoadX = findNearestRoadCoord(targetB.x);
      const destRoadZ = findNearestRoadCoord(targetB.z);

      waypoints.push(new THREE.Vector3(startX, 0, roadZ));
      waypoints.push(new THREE.Vector3(roadX, 0, roadZ));
      if (roadX !== destRoadX) waypoints.push(new THREE.Vector3(destRoadX, 0, roadZ));
      if (roadZ !== destRoadZ) waypoints.push(new THREE.Vector3(destRoadX, 0, destRoadZ));
      waypoints.push(new THREE.Vector3(targetB.x, 0, destRoadZ));
      waypoints.push(new THREE.Vector3(targetB.x, 0, targetB.z));
    }

    residents.push({
      slug: def.slug,
      definition: def,
      rootGroup: residentRoot,
      actorGroup,
      stationGroup,
      leftArm,
      rightArm,
      leftLeg,
      rightLeg,
      gateMesh,
      plaqueTexture: plaqueTex,
      plaqueMaterial: plaqueMat,
      homePos,
      stationPos,
      waypoints,
      currentLeg: 0,
      legProgress: 0,
      walkCycle: 0,
      presence: initialPresence,
    });
  }

  const scratchTarget = new THREE.Vector3();

  let controlledSlug: ResidentSlug | null = null;
  let manuallyMoving = false;
  const markerMaterial = trackMat(new THREE.MeshBasicMaterial({ color: '#ebbd49', depthWrite: false }));
  const marker = new THREE.Mesh(trackGeo(new THREE.TorusGeometry(1.2, 0.09, 8, 36)), markerMaterial);
  marker.rotation.x = -Math.PI / 2;
  marker.visible = false;
  rootGroup.add(marker);
  const controlState = (): CrewControlState => {
    const selected = residents.find(item => item.slug === controlledSlug);
    if (!selected) return { slug: null, x: 0, z: 0, moving: false, nearbySlug: null };
    const position = selected.actorGroup.position;
    const nearest = residents.map(item => ({ slug: item.slug, distance: position.distanceTo(item.stationPos) }))
      .filter(item => item.distance <= 5).sort((a, b) => a.distance - b.distance)[0];
    return { slug: selected.slug, x: position.x, z: position.z, moving: manuallyMoving, nearbySlug: nearest?.slug ?? null };
  };
  return {
    controlState,
    controlResident(slug) {
      const previous = residents.find(item => item.slug === controlledSlug);
      if (previous) {
        previous.actorGroup.position.copy(previous.homePos);
        previous.currentLeg = 0;
        previous.legProgress = 0;
        previous.leftArm.rotation.x = previous.rightArm.rotation.x = previous.leftLeg.rotation.x = previous.rightLeg.rotation.x = 0;
      }
      const selected = residents.find(item => item.slug === slug);
      controlledSlug = selected?.slug ?? null;
      manuallyMoving = false;
      marker.visible = Boolean(selected);
      if (selected) {
        const home = safeCrewHome(selected.homePos, buildings);
        selected.actorGroup.position.set(home.x, 0, home.z);
        marker.position.set(home.x, 0.08, home.z);
        markerMaterial.color.set(selected.definition.color);
      }
    },
    moveResident(input, forward, dt) {
      const selected = residents.find(item => item.slug === controlledSlug);
      if (!selected) return controlState();
      const previous = selected.actorGroup.position.clone();
      const next = navigateCrew(previous, input, forward, dt, buildings);
      selected.actorGroup.position.set(next.x, 0, next.z);
      manuallyMoving = previous.distanceToSquared(selected.actorGroup.position) > 0.000001;
      if (manuallyMoving) selected.actorGroup.rotation.y = Math.atan2(next.x - previous.x, next.z - previous.z);
      if (!reducedMotion && manuallyMoving) selected.walkCycle += Math.max(0, Math.min(dt, 0.1)) * 10;
      const swing = !reducedMotion && manuallyMoving ? Math.sin(selected.walkCycle) * 0.28 : 0;
      selected.leftLeg.rotation.x = selected.rightArm.rotation.x = swing;
      selected.rightLeg.rotation.x = selected.leftArm.rotation.x = -swing;
      marker.position.set(next.x, 0.08, next.z);
      return controlState();
    },
    group: rootGroup,
    pickTargets,

    setPresence(presenceList: readonly ResidentPresence[]) {
      const authoritativePresence = residents.map(res => presenceList.find(p => p.slug === res.slug) || {
        ...res.presence, state: 'unknown' as const, evidence: 'unobserved' as const,
        label: 'Unknown', reason: 'No observed presence for this resident', recordId: null, observedAt: null,
      });
      for (const p of authoritativePresence) {
        const res = residents.find((r) => r.slug === p.slug);
        if (!res) continue;

        const prevPresence = res.presence;
        res.presence = { ...p };

        const changed =
          prevPresence.state !== p.state ||
          prevPresence.label !== p.label ||
          prevPresence.evidence !== p.evidence;

        if (changed) {
          const newCanvas = createPlaqueCanvas(res.definition.slug.toUpperCase(), res.definition.station, p);
          res.plaqueTexture.image = newCanvas;
          res.plaqueTexture.needsUpdate = true;

          if (prevPresence.state !== p.state) {
            res.currentLeg = 0;
            res.legProgress = 0;
            if (res.slug !== controlledSlug) res.actorGroup.position.copy(res.homePos);
          }
          if (p.state === 'held') {
            res.gateMesh.visible = true;
            if (res.slug !== controlledSlug) res.actorGroup.position.copy(res.homePos);
            res.leftArm.rotation.x = 0;
            res.rightArm.rotation.x = 0;
            res.leftLeg.rotation.x = 0;
            res.rightLeg.rotation.x = 0;
          } else {
            res.gateMesh.visible = false;
            if (p.state !== 'active') {
              if (res.slug !== controlledSlug) res.actorGroup.position.copy(res.homePos);
              res.leftArm.rotation.x = 0;
              res.rightArm.rotation.x = 0;
              res.leftLeg.rotation.x = 0;
              res.rightLeg.rotation.x = 0;
            }
          }
        }
      }
    },

    update(dt: number, mode: GameState['mode']) {
      rootGroup.visible = mode === 'explore';
      if (!rootGroup.visible) return;

      const safeDt = Number.isFinite(dt) ? Math.max(0, Math.min(dt, MAX_DT)) : 0;

      for (const res of residents) {
        if (res.slug === controlledSlug || reducedMotion || res.presence.state !== 'active' || res.waypoints.length < 2) {
          continue;
        }

        let distToTravel = safeDt * SPEED;
        let steps = 0;
        while (distToTravel > 0 && res.waypoints.length >= 2 && steps++ <= res.waypoints.length + 1) {
          const p1 = res.waypoints[res.currentLeg];
          const nextIndex = (res.currentLeg + 1) % res.waypoints.length;
          const p2 = res.waypoints[nextIndex];

          const legDist = p1.distanceTo(p2);
          if (legDist < 0.0001) {
            res.currentLeg = nextIndex;
            res.legProgress = 0;
            continue;
          }

          const currentDistAlong = res.legProgress * legDist;
          const remainingDistOnLeg = legDist - currentDistAlong;

          if (distToTravel >= remainingDistOnLeg) {
            distToTravel -= remainingDistOnLeg;
            res.currentLeg = nextIndex;
            res.legProgress = 0;
            res.actorGroup.position.copy(p2);
          } else {
            res.legProgress += distToTravel / legDist;
            res.actorGroup.position.lerpVectors(p1, p2, res.legProgress);
            distToTravel = 0;
          }

          scratchTarget.subVectors(p2, p1);
          if (scratchTarget.lengthSq() > 0.001) {
            const angle = Math.atan2(scratchTarget.x, scratchTarget.z);
            res.actorGroup.rotation.y = angle;
          }
        }

        // Walk animation (limbs max 0.28 rad)
        res.walkCycle += safeDt * 7.5;
        const swing = Math.sin(res.walkCycle) * 0.28;
        res.leftLeg.rotation.x = swing;
        res.rightLeg.rotation.x = -swing;
        res.leftArm.rotation.x = -swing;
        res.rightArm.rotation.x = swing;
      }
    },

    dispose() {
      if (rootGroup.parent) {
        rootGroup.parent.remove(rootGroup);
      }
      for (const g of allocatedGeometries) g.dispose();
      for (const m of allocatedMaterials) m.dispose();
      for (const t of allocatedTextures) t.dispose();
      allocatedGeometries.clear();
      allocatedMaterials.clear();
      allocatedTextures.clear();
      pickTargets.length = 0;
      residents.length = 0;
    },
  };
}
