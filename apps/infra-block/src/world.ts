import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Layer, InfraNode, GameState, WorldEvent, WorldController, CharacterId } from './contracts';
import { createCharacter, CharacterInstance } from './characters';
import { RESIDENTS, type ResidentPresence } from './residents';
import { createResidentCrew } from './resident-characters';

function makePrng(seedStr: string) {
  let h = 1779033703 ^ seedStr.length;
  for (let i = 0; i < seedStr.length; i++) {
    h = Math.imul(h ^ seedStr.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 16), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

export function createWorld(
  container: HTMLElement,
  nodes: InfraNode[],
  initialState: GameState,
  onSelect: (id: string) => void
): WorldController {
  const rand = makePrng(initialState.seed || 'pastel_city');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const nodeMap = new Map<string, InfraNode>(nodes.map(n => [n.id, n]));

  // Renderer & Scene setup
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#fdf9f2');

  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 500);
  camera.position.set(35, 37, 41);

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.65));
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !reducedMotion;
  controls.dampingFactor = 0.08;
  controls.minDistance = 48;
  controls.maxDistance = 100;
  controls.enablePan = false;
  controls.maxPolarAngle = Math.PI / 2.1;
  controls.target.set(0, 0, 0);
  let focusTarget: THREE.Vector3 | null = null;
  let focusDistance: number | null = null;
  let focusDirection: THREE.Vector3 | null = null;
  const townDirection = new THREE.Vector3(35, 37, 41).normalize();
  let fittedDistance = 90;
  let fittedMinDistance = 48;
  let followSuspended = false;
  let overlayWasOpen = false;
  const hasOverlay = () => ['field-kit-open', 'source-notes-open', 'home-encounter-open'].some(name => document.body.classList.contains(name)) || Boolean(document.querySelector('dialog[open]'));
  const onWorldFocus = (event: Event) => {
    const id = (event as CustomEvent<string | null>).detail;
    const controlled = residents.controlState();
    followSuspended = Boolean(id && controlled.slug);
    if (!id && controlled.slug) {
      controls.minDistance = 18;
      focusDistance = 29;
      focusDirection = new THREE.Vector3(14, 34, 16).normalize();
      focusTarget = new THREE.Vector3(controlled.x, 1.8, controlled.z);
      return;
    }
    const building = id ? buildingObjs.find(item => item.id === id) : null;
    const resident = RESIDENTS.find(item => item.nodeId === id);
    const station = resident ? residents.group.getObjectByName(`Station_${resident.slug}`) : null;
    controls.minDistance = station ? 24 : fittedMinDistance;
    focusDistance = station ? 36 : fittedDistance;
    focusDirection = station ? new THREE.Vector3(14, 34, 16).normalize() : townDirection.clone();
    focusTarget = station ? new THREE.Vector3(station.position.x, 1.5, station.position.z) : building
      ? new THREE.Vector3(building.group.position.x * 0.35, 3, building.group.position.z * 0.35)
      : new THREE.Vector3(0, 3, 0);
  };
  const cancelFocus = () => { focusTarget = null; focusDistance = null; focusDirection = null; };
  container.addEventListener('world-focus', onWorldFocus);
  controls.addEventListener('start', cancelFocus);

  // Lights
  const hemiLight = new THREE.HemisphereLight('#ffffff', '#dfd2c0', 1.8);
  scene.add(hemiLight);

  const dirLight = new THREE.DirectionalLight('#fffaf0', 2.0);
  dirLight.position.set(32, 50, 24);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  dirLight.shadow.bias = -0.0003;
  dirLight.shadow.camera.near = 10;
  dirLight.shadow.camera.far = 140;
  const d = 34;
  dirLight.shadow.camera.left = -d;
  dirLight.shadow.camera.right = d;
  dirLight.shadow.camera.top = d;
  dirLight.shadow.camera.bottom = -d;
  scene.add(dirLight);

  // Base Platform: beveled cream slab
  const platGeo = new RoundedBoxGeometry(52.6, 1.6, 52.6, 4, 0.6);
  const platMat = new THREE.MeshStandardMaterial({ color: '#f3ede1', roughness: 0.95, metalness: 0 });
  const platform = new THREE.Mesh(platGeo, platMat);
  platform.position.y = -0.8;
  platform.receiveShadow = true;
  scene.add(platform);

  // Sage Avenues Grid
  const gridGroup = new THREE.Group();
  const avenueCoords = [-20.8, -10.4, 0, 10.4, 20.8];
  const roadMat = new THREE.MeshStandardMaterial({ color: '#a6b8a8', roughness: 0.95, metalness: 0 });
  const lineMat = new THREE.MeshBasicMaterial({ color: '#fbfcf8' });

  avenueCoords.forEach(pos => {
    const roadX = new THREE.Mesh(new THREE.PlaneGeometry(52.6, 3.3), roadMat);
    roadX.rotation.x = -Math.PI / 2;
    roadX.position.set(0, 0.01, pos);
    roadX.receiveShadow = true;
    gridGroup.add(roadX);

    const roadZ = new THREE.Mesh(new THREE.PlaneGeometry(3.3, 52.6), roadMat);
    roadZ.rotation.x = -Math.PI / 2;
    roadZ.position.set(pos, 0.015, 0);
    roadZ.receiveShadow = true;
    gridGroup.add(roadZ);

    for (let k = -24; k <= 24; k += 4) {
      const dashH = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 0.18), lineMat);
      dashH.rotation.x = -Math.PI / 2;
      dashH.position.set(k, 0.02, pos);
      gridGroup.add(dashH);

      const dashV = new THREE.Mesh(new THREE.PlaneGeometry(0.18, 1.8), lineMat);
      dashV.rotation.x = -Math.PI / 2;
      dashV.position.set(pos, 0.025, k);
      gridGroup.add(dashV);
    }
  });
  scene.add(gridGroup);

  // Clouds at high outer edge
  const cloudsGroup = new THREE.Group();
  const cloudMat = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 0.9, transparent: true, opacity: 0.65 });
  for (let i = 0; i < 7; i++) {
    const ang = (i / 7) * Math.PI * 2 + rand();
    const rad = 32 + rand() * 5;
    const cMesh = new THREE.Mesh(new THREE.SphereGeometry(2.4 + rand() * 1.5, 8, 8), cloudMat);
    cMesh.position.set(Math.cos(ang) * rad, 18 + rand() * 4, Math.sin(ang) * rad);
    cMesh.scale.set(1.6, 0.6, 1.2);
    cloudsGroup.add(cMesh);
  }
  cloudsGroup.visible = false;
  scene.add(cloudsGroup);

  // Street Props: Trees, Lamps, Benches, Bollards
  const propsGroup = new THREE.Group();
  const treeTrunkGeo = new THREE.CylinderGeometry(0.12, 0.16, 1.1, 6);
  const treeTrunkMat = new THREE.MeshStandardMaterial({ color: '#7a5c43', roughness: 0.95 });
  const treeCanopyGeo = new THREE.SphereGeometry(0.85, 12, 10);
  const treeCanopyMat = new THREE.MeshStandardMaterial({ color: '#789a74', roughness: 0.95 });
  const lampPoleGeo = new THREE.CylinderGeometry(0.05, 0.07, 1.6, 6);
  const lampPoleMat = new THREE.MeshStandardMaterial({ color: '#556660', roughness: 0.8 });
  const lampGlobeGeo = new THREE.SphereGeometry(0.2, 8, 8);
  const lampGlobeMat = new THREE.MeshStandardMaterial({ color: '#fff9db', roughness: 0.3, emissive: '#fff9db', emissiveIntensity: 0.4 });
  const benchGeo = new THREE.BoxGeometry(0.8, 0.25, 0.35);
  const benchMat = new THREE.MeshStandardMaterial({ color: '#b58863', roughness: 0.9 });

  for (const ax of [-18, -6, 6, 18]) {
    for (const az of [-18, -6, 6, 18]) {
      const tTrunk = new THREE.Mesh(treeTrunkGeo, treeTrunkMat);
      const tCanopy = new THREE.Mesh(treeCanopyGeo, treeCanopyMat);
      tTrunk.position.set(ax + 2.5, 0.55, az + 2.5);
      tCanopy.position.set(ax + 2.5, 1.6, az + 2.5);
      tTrunk.castShadow = true;
      tCanopy.castShadow = true;
      propsGroup.add(tTrunk, tCanopy);

      const lPole = new THREE.Mesh(lampPoleGeo, lampPoleMat);
      const lGlobe = new THREE.Mesh(lampGlobeGeo, lampGlobeMat);
      lPole.position.set(ax - 2.5, 0.8, az + 2.5);
      lGlobe.position.set(ax - 2.5, 1.65, az + 2.5);
      lPole.castShadow = true;
      propsGroup.add(lPole, lGlobe);

      if (rand() > 0.4) {
        const bench = new THREE.Mesh(benchGeo, benchMat);
        bench.position.set(ax + 2.4, 0.15, az - 2.4);
        bench.castShadow = true;
        propsGroup.add(bench);
      }
    }
  }
  scene.add(propsGroup);

  // Building Signs Texture Factory
  function createSignTexture(text: string, short: string): THREE.CanvasTexture {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 160;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, 512, 160);
    ctx.fillStyle = '#243b35';
    ctx.font = 'bold 56px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText((short || text.slice(0, 5)).toUpperCase(), 256, 68);
    ctx.font = '600 30px sans-serif';
    ctx.fillStyle = '#486259';
    ctx.fillText(text.slice(0, 20), 256, 126);
    return new THREE.CanvasTexture(canvas);
  }

  function createAwningTexture(): THREE.CanvasTexture {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = '#f6edd9';
    ctx.fillRect(0, 0, 128, 128);
    ctx.fillStyle = '#658d7c';
    for (let i = 0; i < 128; i += 32) ctx.fillRect(i, 0, 16, 128);
    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = THREE.RepeatWrapping;
    tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2, 1);
    return tex;
  }

  // Buildings Creation
  interface BuildingObj {
    id: string;
    height: number;
    group: THREE.Group;
    bodyMesh: THREE.Mesh;
    materials: THREE.Material[];
    targetY: number;
    currentY: number;
    recoil: number;
    nodeLayer: Layer;
  }

  const buildingObjs: BuildingObj[] = [];
  const buildingGroup = new THREE.Group();
  scene.add(buildingGroup);

  initialState.buildings.forEach((bs, bIdx) => {
    const node = nodeMap.get(bs.id);
    const bGroup = new THREE.Group();
    bGroup.position.set(bs.x, 0, bs.z);
    bGroup.userData = { id: bs.id };

    const colorHex = node?.color ? new THREE.Color(node.color).lerp(new THREE.Color('#ffffff'), 0.1) : new THREE.Color('#e0d5c1');
    const bodyMat = new THREE.MeshStandardMaterial({ color: colorHex, roughness: 0.95, metalness: 0 });
    const bGeo = new RoundedBoxGeometry(bs.width, bs.height, bs.depth, 3, 0.25);
    const bodyMesh = new THREE.Mesh(bGeo, bodyMat);
    bodyMesh.position.y = bs.height / 2;
    bodyMesh.castShadow = true;
    bodyMesh.receiveShadow = true;
    bGroup.add(bodyMesh);

    const winMat = new THREE.MeshStandardMaterial({ color: '#27494f', roughness: 0.4, metalness: 0.1 });
    const winRows = Math.max(1, bs.floors);
    const winCols = Math.max(2, Math.floor(bs.width / 1.15));
    for (let r = 0; r < winRows; r++) {
      const wy = (r + 0.5) * (bs.height / winRows) - bs.height / 2;
      for (let c = 0; c < winCols; c++) {
        const wx = (c - (winCols - 1) / 2) * (bs.width / (winCols + 0.3));
        const wMeshFront = new THREE.Mesh(new THREE.PlaneGeometry(0.65, 0.72), winMat);
        wMeshFront.position.set(wx, wy, bs.depth / 2 + 0.02);
        bodyMesh.add(wMeshFront);

        const wMeshSide = new THREE.Mesh(new THREE.PlaneGeometry(0.65, 0.72), winMat);
        wMeshSide.rotation.y = Math.PI / 2;
        wMeshSide.position.set(bs.width / 2 + 0.02, wy, wx * (bs.depth / bs.width));
        bodyMesh.add(wMeshSide);
      }
    }

    // Door & Awning
    const door = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 1.2), new THREE.MeshStandardMaterial({ color: '#4a382c', roughness: 0.9 }));
    door.position.set(0, -bs.height / 2 + 0.6, bs.depth / 2 + 0.02);
    bodyMesh.add(door);

    const awningMat = new THREE.MeshStandardMaterial({ map: createAwningTexture(), roughness: 0.85 });
    const awning = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.14, 0.7), awningMat);
    awning.position.set(0, -bs.height / 2 + 1.35, bs.depth / 2 + 0.35);
    awning.castShadow = true;
    bodyMesh.add(awning);

    // Varied deterministic Roofs & Rooftop elements
    const rStyle = (bIdx + bs.id.charCodeAt(0)) % 4;
    const slateMat = new THREE.MeshStandardMaterial({ color: ['#3e4f52', '#515e61', '#42454f', '#4e5b53'][rStyle], roughness: 0.85 });
    if (rStyle === 0) {
      const gGeo = new THREE.ConeGeometry(Math.max(bs.width, bs.depth) * 0.72, 1.4, 4);
      gGeo.rotateY(Math.PI / 4);
      const gRoof = new THREE.Mesh(gGeo, slateMat);
      gRoof.position.set(0, bs.height / 2 + 0.7, 0);
      gRoof.castShadow = true;
      bodyMesh.add(gRoof);
    } else if (rStyle === 1) {
      const parGeo = new THREE.BoxGeometry(bs.width + 0.1, 0.28, bs.depth + 0.1);
      const parapet = new THREE.Mesh(parGeo, slateMat);
      parapet.position.set(0, bs.height / 2 + 0.14, 0);
      parapet.castShadow = true;
      bodyMesh.add(parapet);
      const solGeo = new THREE.BoxGeometry(bs.width * 0.5, 0.08, bs.depth * 0.45);
      const sol = new THREE.Mesh(solGeo, new THREE.MeshStandardMaterial({ color: '#1f3448', roughness: 0.3, metalness: 0.5 }));
      sol.position.set(0, bs.height / 2 + 0.2, 0);
      sol.rotation.x = 0.2;
      bodyMesh.add(sol);
    } else if (rStyle === 2) {
      [-bs.width * 0.25, bs.width * 0.25].forEach(cx => {
        const ch = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.8, 0.35), slateMat);
        ch.position.set(cx, bs.height / 2 + 0.4, -bs.depth * 0.2);
        ch.castShadow = true;
        bodyMesh.add(ch);
      });
    } else {
      const topSign = new THREE.Mesh(new THREE.BoxGeometry(bs.width * 0.65, 0.4, 0.1), slateMat);
      topSign.position.set(0, bs.height / 2 + 0.2, 0);
      bodyMesh.add(topSign);
    }

    const ac = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.45, 0.55), new THREE.MeshStandardMaterial({ color: '#cfc6bb', roughness: 0.85 }));
    ac.position.set(bs.width * 0.22, bs.height / 2 + 0.23, bs.depth * 0.22);
    ac.castShadow = true;
    bodyMesh.add(ac);

    // Sign parented correctly to body mesh
    const signTex = createSignTexture(node?.name || bs.id, node?.short || bs.id);
    const signMat = new THREE.MeshStandardMaterial({ map: signTex, roughness: 0.85 });
    const signMesh = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(3.2, bs.width * 0.88), 0.8), signMat);
    signMesh.position.set(0, bs.height * 0.2, bs.depth / 2 + 0.06);
    bodyMesh.add(signMesh);

    const mats: THREE.Material[] = [];
    bodyMesh.traverse(child => {
      if (child instanceof THREE.Mesh && child.material) {
        if (Array.isArray(child.material)) child.material.forEach(m => mats.push(m));
        else mats.push(child.material);
      }
    });

    buildingGroup.add(bGroup);
    buildingObjs.push({
      id: bs.id,
      height: bs.height,
      group: bGroup,
      bodyMesh,
      materials: mats,
      targetY: 0,
      currentY: 0,
      recoil: 0,
      nodeLayer: node?.layer || 'runtime'
    });
  });

  // Selection Ring
  const ringGeo = new THREE.RingGeometry(2.6, 3.2, 32);
  ringGeo.rotateX(-Math.PI / 2);
  const ringMat = new THREE.MeshBasicMaterial({ color: '#ffcc00', side: THREE.DoubleSide });
  const selectRing = new THREE.Mesh(ringGeo, ringMat);
  selectRing.position.y = 0.06;
  selectRing.visible = false;
  scene.add(selectRing);

  // Cars
  interface CarObj {
    id: number;
    group: THREE.Group;
    body: THREE.Mesh;
  }
  const carGroup = new THREE.Group();
  scene.add(carGroup);
  const carObjs: CarObj[] = [];
  const carColors = ['#e05c5c', '#4682b4', '#55a66a', '#e5983b', '#8e6bb3'];

  initialState.cars.forEach((cs, idx) => {
    const cg = new THREE.Group();
    const cMat = new THREE.MeshStandardMaterial({ color: carColors[idx % carColors.length], roughness: 0.7 });
    const cbGeo = new THREE.BoxGeometry(1.4, 0.5, 0.9);
    const cbMesh = new THREE.Mesh(cbGeo, cMat);
    cbMesh.position.y = 0.35;
    cbMesh.castShadow = true;
    cg.add(cbMesh);

    const cTop = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.35, 0.75), new THREE.MeshStandardMaterial({ color: '#334448', roughness: 0.4 }));
    cTop.position.set(-0.1, 0.65, 0);
    cg.add(cTop);

    const wGeo = new THREE.CylinderGeometry(0.18, 0.18, 0.12, 10);
    wGeo.rotateX(Math.PI / 2);
    const wMat = new THREE.MeshStandardMaterial({ color: '#222222', roughness: 0.9 });
    [[-0.45, 0.4], [0.45, 0.4], [-0.45, -0.4], [0.45, -0.4]].forEach(([wx, wz]) => {
      const wheel = new THREE.Mesh(wGeo, wMat);
      wheel.position.set(wx, 0.18, wz);
      cg.add(wheel);
    });

    cg.position.set(cs.x, 0, cs.z);
    carGroup.add(cg);
    carObjs.push({ id: cs.id, group: cg, body: cbMesh });
  });

  // Active Character
  let currentCharId: CharacterId = initialState.character;
  let activeChar: CharacterInstance = createCharacter(currentCharId);
  scene.add(activeChar.group);
  let prevPlayerPos = { x: initialState.player.x, z: initialState.player.z };

  // Particle Debris & Rings
  interface ParticleDebris {
    mesh: THREE.Mesh;
    vx: number;
    vy: number;
    vz: number;
    life: number;
    maxLife: number;
  }
  interface RingWave {
    mesh: THREE.Mesh;
    life: number;
    maxLife: number;
  }
  const debrisList: ParticleDebris[] = [];
  const ringList: RingWave[] = [];
  const debrisGeo = new THREE.BoxGeometry(0.25, 0.25, 0.25);
  const ringWaveGeo = new THREE.RingGeometry(0.2, 0.4, 24);
  ringWaveGeo.rotateX(-Math.PI / 2);

  // Role residents use source-defined homes and relationships, never game collision state.
  const residents = createResidentCrew(RESIDENTS, initialState.buildings, reducedMotion);
  scene.add(residents.group);
  let residentsEnabled = true;
  const onResidentPresence = (event: Event) => {
    const presence = (event as CustomEvent<ResidentPresence[]>).detail;
    if (Array.isArray(presence)) residents.setPresence(presence);
  };
  const onResidentVisibility = (event: Event) => {
    residentsEnabled = (event as CustomEvent<boolean>).detail === true;
    if (!residentsEnabled) residents.group.visible = false;
  };
  container.addEventListener('resident-presence', onResidentPresence);
  container.addEventListener('resident-visible', onResidentVisibility);

  // Route Ribbons
  let routeGroup: THREE.Group | null = null;
  let routeCurve: THREE.CatmullRomCurve3 | null = null;
  let routeOrb: THREE.Mesh | null = null;
  let routeProgress = 0;

  // Raycasting & Pointer Suppressed Drag Click
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let pointerDownPos = { x: 0, y: 0 };

  const onPointerDown = (e: MouseEvent) => {
    pointerDownPos = { x: e.clientX, y: e.clientY };
  };

  const onPointerUp = (e: MouseEvent) => {
    const dx = e.clientX - pointerDownPos.x;
    const dy = e.clientY - pointerDownPos.y;
    if (Math.hypot(dx, dy) > 5) return;

    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(pointer, camera);
    const residentSlug = pickResident();
    if (residentSlug) {
      container.dispatchEvent(new CustomEvent('resident-select', { detail: { slug: residentSlug } }));
      return;
    }
    const intersects = raycaster.intersectObjects(buildingGroup.children, true);
    if (intersects.length > 0) {
      let cur: THREE.Object3D | null = intersects[0].object;
      while (cur && cur.parent && cur.parent !== buildingGroup) {
        cur = cur.parent;
      }
      if (cur && cur.userData && typeof cur.userData.id === 'string') {
        onSelect(cur.userData.id);
      }
    }
  };

  function pickResident(): string | null {
    if (!residents.group.visible || !residentsEnabled) return null;
    const hit = raycaster.intersectObjects(residents.pickTargets, true)[0];
    if (!hit) return null;
    const obstruction = raycaster.intersectObjects(buildingObjs.map(item => item.group), true)[0];
    if (obstruction && obstruction.distance < hit.distance - 0.05) return null;
    let target: THREE.Object3D | null = hit.object;
    while (target && target !== residents.group) {
      if (typeof target.userData.residentSlug === 'string') return target.userData.residentSlug;
      target = target.parent;
    }
    return null;
  }
  const onPointerMove = (event: PointerEvent) => {
    const rect = renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    renderer.domElement.style.cursor = pickResident() ? 'pointer' : 'grab';
  };

  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  renderer.domElement.addEventListener('pointerup', onPointerUp);
  renderer.domElement.addEventListener('pointermove', onPointerMove);

  // Resize handling
  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.contentRect.width || container.clientWidth || 300;
      const height = entry.contentRect.height || container.clientHeight || 300;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      const fitCamera = camera.clone();
      const fitTarget = new THREE.Vector3(0, 3, 0);
      let distance = 60;
      for (let i = 0; i < 24; i++) {
        fitCamera.position.copy(fitTarget).addScaledVector(townDirection, distance);
        fitCamera.lookAt(fitTarget);
        fitCamera.updateMatrixWorld();
        let fits = true;
        for (const x of [-26.3, 26.3]) for (const z of [-26.3, 26.3]) for (const y of [-1.6, 8]) {
          const point = new THREE.Vector3(x, y, z).project(fitCamera);
          if (Math.abs(point.x) > 1.08 || Math.abs(point.y) > 1.04) fits = false;
        }
        if (fits) break;
        distance *= 1.06;
      }
      fittedDistance = distance;
      fittedMinDistance = Math.max(48, distance * 0.7);
      const controlled = residents.controlState();
      if (!controlled.slug && !focusTarget) camera.position.copy(controls.target).addScaledVector(townDirection, distance);
      controls.minDistance = controlled.slug ? 18 : focusDistance === 36 ? 24 : fittedMinDistance;
      controls.maxDistance = distance * 1.7;
    }
  });
  resizeObserver.observe(container);

  // Return Controller
  return {
    controlResident(slug: string | null) {
      residents.controlResident(slug);
      const selectedSlug = residents.controlState().slug;
      focusTarget = null;
      focusDirection = null;
      focusDistance = null;
      controls.minDistance = selectedSlug ? 18 : fittedMinDistance;
      onWorldFocus(new CustomEvent('world-focus', { detail: selectedSlug ? RESIDENTS.find(item => item.slug === selectedSlug)?.nodeId ?? null : null }));
      if (selectedSlug) {
        followSuspended = false;
        controls.minDistance = 18;
        focusDistance = 29;
      }
    },
    moveResident(x: number, z: number, dt: number) {
      if ((x || z) && followSuspended && !hasOverlay()) onWorldFocus(new CustomEvent('world-focus', { detail: null }));
      const forward = camera.getWorldDirection(new THREE.Vector3());
      return residents.moveResident({ x, z: -z }, { x: forward.x, z: forward.z }, dt);
    },
    update(state: GameState, dt: number) {
      residents.update(dt, residentsEnabled ? state.mode : 'playing');
      if (!residentsEnabled) residents.group.visible = false;
      const controlled = residents.controlState();
      const overlayOpen = hasOverlay();
      if (controlled.slug && overlayWasOpen && !overlayOpen) onWorldFocus(new CustomEvent('world-focus', { detail: null }));
      overlayWasOpen = overlayOpen;
      const followAllowed = Boolean(controlled.slug && !overlayOpen && !followSuspended);
      if (followAllowed && focusTarget) focusTarget.set(controlled.x, 1.8, controlled.z);
      if (focusTarget) {
        const previous = controls.target.clone();
        controls.target.lerp(focusTarget, reducedMotion ? 1 : 1 - Math.exp(-Math.min(dt, 0.1) * 5));
        camera.position.add(controls.target.clone().sub(previous));
        const alpha = reducedMotion ? 1 : 1 - Math.exp(-Math.min(dt, 0.1) * 5);
        const offset = camera.position.clone().sub(controls.target);
        const desiredDistance = focusDistance ?? offset.length();
        const nextDistance = THREE.MathUtils.lerp(offset.length(), desiredDistance, alpha);
        const direction = offset.normalize();
        if (focusDirection) direction.lerp(focusDirection, alpha).normalize();
        camera.position.copy(controls.target).addScaledVector(direction, nextDistance);
        if (controls.target.distanceToSquared(focusTarget) < 0.002 && Math.abs(nextDistance - desiredDistance) < 0.02 && (!focusDirection || direction.distanceToSquared(focusDirection) < 0.00001)) {
          focusTarget = null;
          focusDistance = null;
          focusDirection = null;
        }
      }
      if (followAllowed && state.mode === 'explore') {
        const alpha = reducedMotion ? 1 : 1 - Math.exp(-Math.min(dt, 0.1) * 7);
        const target = new THREE.Vector3(controlled.x, 1.8, controlled.z);
        const previous = controls.target.clone();
        controls.target.lerp(target, alpha);
        camera.position.add(controls.target.clone().sub(previous));
      }
      controls.update();

      // Character Switch
      if (state.character !== currentCharId) {
        scene.remove(activeChar.group);
        activeChar.dispose();
        currentCharId = state.character;
        activeChar = createCharacter(currentCharId);
        scene.add(activeChar.group);
      }

      // Player Animation
      const moved = Math.hypot(state.player.x - prevPlayerPos.x, state.player.z - prevPlayerPos.z) > 0.001;
      prevPlayerPos = { x: state.player.x, z: state.player.z };
      activeChar.group.visible = true;
      const visualPlayer = state.mode === 'explore' ? { x: 0, z: 20.8, angle: 0.25 } : state.player;
      activeChar.group.scale.setScalar(state.mode === 'explore' ? 1.8 : 1.5);
      activeChar.animate(reducedMotion ? 0 : dt, visualPlayer, state.mode === 'playing' && !reducedMotion && moved);

      // Clouds drift
      if (!reducedMotion) cloudsGroup.rotation.y += dt * 0.02;

      // Update Buildings
      const stateBMap = new Map(state.buildings.map(b => [b.id, b]));
      buildingObjs.forEach(b => {
        const bs = stateBMap.get(b.id);
        if (bs) {
          if (bs.destroyed) {
            b.targetY = -bs.height * 0.7;
            b.bodyMesh.scale.y = THREE.MathUtils.lerp(b.bodyMesh.scale.y, 0.25, dt * 6);
          } else {
            b.targetY = 0;
            b.bodyMesh.scale.y = THREE.MathUtils.lerp(b.bodyMesh.scale.y, 1.0, dt * 6);
          }
        }
        if (b.recoil > 0) {
          b.recoil = Math.max(0, b.recoil - dt * 4);
          b.group.position.y = THREE.MathUtils.lerp(b.group.position.y, b.targetY + Math.sin(b.recoil * 18) * 0.2, dt * 12);
        } else {
          b.group.position.y = THREE.MathUtils.lerp(b.group.position.y, b.targetY, dt * 6);
        }
      });

      // Update Cars
      const carStateMap = new Map(state.cars.map(c => [c.id, c]));
      carObjs.forEach(co => {
        const cs = carStateMap.get(co.id);
        if (!cs || cs.state === 'destroyed') {
          co.group.visible = false;
        } else if (cs.state === 'held') {
          co.group.visible = true;
          co.group.position.set(state.player.x, 2.4, state.player.z);
          co.group.rotation.y = state.player.angle;
        } else if (cs.state === 'airborne') {
          co.group.visible = true;
          co.group.position.set(cs.x, 1.8, cs.z);
          co.group.rotation.x += dt * 5;
        } else {
          co.group.visible = true;
          co.group.position.set(cs.x, 0, cs.z);
        }
      });

      // Update Particles
      for (let i = debrisList.length - 1; i >= 0; i--) {
        const p = debrisList[i];
        p.life += dt;
        if (p.life >= p.maxLife) {
          scene.remove(p.mesh);
          (p.mesh.material as THREE.Material).dispose();
          debrisList.splice(i, 1);
        } else {
          p.mesh.position.x += p.vx * dt;
          p.mesh.position.y += p.vy * dt;
          p.mesh.position.z += p.vz * dt;
          p.vy -= 9.8 * dt;
          p.mesh.rotation.x += dt * 3;
          p.mesh.rotation.y += dt * 4;
          const s = (1 - p.life / p.maxLife);
          p.mesh.scale.set(s, s, s);
        }
      }

      // Update Rings
      for (let i = ringList.length - 1; i >= 0; i--) {
        const r = ringList[i];
        r.life += dt;
        if (r.life >= r.maxLife) {
          scene.remove(r.mesh);
          (r.mesh.material as THREE.Material).dispose();
          ringList.splice(i, 1);
        } else {
          const progress = r.life / r.maxLife;
          const scale = 1 + progress * 4.5;
          r.mesh.scale.set(scale, 1, scale);
          (r.mesh.material as THREE.MeshBasicMaterial).opacity = 1 - progress;
        }
      }

      // Route Ribbon Orb Animation
      if (routeOrb && routeCurve) {
        if (!reducedMotion) routeProgress = (routeProgress + dt * 0.35) % 1;
        const pt = routeCurve.getPoint(routeProgress);
        routeOrb.position.copy(pt);
      }

      renderer.render(scene, camera);
    },

    event(ev: WorldEvent) {
      if (ev.type === 'hit' || ev.type === 'demolish' || ev.type === 'stomp') {
        if (ev.id) {
          const b = buildingObjs.find(bo => bo.id === ev.id);
          if (b) b.recoil = 1.0;
        }
        // Spawn Ring
        if (ringList.length < 8) {
          const rMat = new THREE.MeshBasicMaterial({
            color: ev.type === 'demolish' ? '#ff4d4d' : '#ffe169',
            transparent: true,
            opacity: 0.9,
            side: THREE.DoubleSide
          });
          const rm = new THREE.Mesh(ringWaveGeo, rMat);
          rm.position.set(ev.x, 0.08, ev.z);
          scene.add(rm);
          ringList.push({ mesh: rm, life: 0, maxLife: 0.85 });
        }
        if (reducedMotion) return;
        // Spawn Debris
        const count = ev.type === 'demolish' ? 14 : 6;
        for (let i = 0; i < count && debrisList.length < 72; i++) {
          const pMat = new THREE.MeshStandardMaterial({
            color: ev.type === 'demolish' ? '#d88b77' : '#e0c896',
            roughness: 0.9
          });
          const pMesh = new THREE.Mesh(debrisGeo, pMat);
          pMesh.position.set(ev.x + (rand() - 0.5) * 0.8, 0.8 + rand(), ev.z + (rand() - 0.5) * 0.8);
          scene.add(pMesh);
          debrisList.push({
            mesh: pMesh,
            vx: (rand() - 0.5) * 9,
            vy: 4 + rand() * 6,
            vz: (rand() - 0.5) * 9,
            life: 0,
            maxLife: 0.7 + rand() * 0.5
          });
        }
      }
    },

    select(id: string | null) {
      if (!id) {
        selectRing.visible = false;
        return;
      }
      const b = buildingObjs.find(bo => bo.id === id);
      if (b) {
        selectRing.position.set(b.group.position.x, 0.06, b.group.position.z);
        selectRing.visible = true;
      } else {
        selectRing.visible = false;
      }
    },

    filter(layer: Layer | 'all') {
      buildingObjs.forEach(b => {
        const match = layer === 'all' || b.nodeLayer === layer;
        const alpha = match ? 1.0 : 0.15;
        b.materials.forEach(m => {
          m.transparent = alpha < 1.0;
          m.opacity = alpha;
          m.depthWrite = alpha >= 0.99;
        });
      });
    },

    route(ids: string[]) {
      if (routeGroup) {
        scene.remove(routeGroup);
        routeGroup.traverse(c => {
          if (c instanceof THREE.Mesh) {
            c.geometry.dispose();
            (c.material as THREE.Material).dispose();
          }
        });
        routeGroup = null;
        routeCurve = null;
        routeOrb = null;
      }
      if (!ids || ids.length < 2) return;

      const points: THREE.Vector3[] = [];
      for (let i = 0; i < ids.length; i++) {
        const b = buildingObjs.find(bo => bo.id === ids[i]);
        if (b) {
          const p = new THREE.Vector3(b.group.position.x, b.height + 1.2, b.group.position.z);
          if (points.length > 0) {
            const prev = points[points.length - 1];
            const mid = new THREE.Vector3((prev.x + p.x) / 2, Math.max(prev.y, p.y) + 1.0, (prev.z + p.z) / 2);
            points.push(mid);
          }
          points.push(p);
        }
      }
      if (points.length < 2) return;

      routeCurve = new THREE.CatmullRomCurve3(points);
      const tubeGeo = new THREE.TubeGeometry(routeCurve, 64, 0.12, 8, false);
      const tubeMat = new THREE.MeshBasicMaterial({ color: '#22d8e6', transparent: true, opacity: 0.88 });
      const tubeMesh = new THREE.Mesh(tubeGeo, tubeMat);

      const orbGeo = new THREE.SphereGeometry(0.25, 12, 12);
      const orbMat = new THREE.MeshBasicMaterial({ color: '#ffffff' });
      routeOrb = new THREE.Mesh(orbGeo, orbMat);

      routeGroup = new THREE.Group();
      routeGroup.add(tubeMesh, routeOrb);
      scene.add(routeGroup);
    },

    reset(state: GameState) {
      this.filter('all');
      this.select(null);
      this.route([]);

      debrisList.forEach(p => {
        scene.remove(p.mesh);
        (p.mesh.material as THREE.Material).dispose();
      });
      debrisList.length = 0;

      ringList.forEach(r => {
        scene.remove(r.mesh);
        (r.mesh.material as THREE.Material).dispose();
      });
      ringList.length = 0;

      const stateBMap = new Map(state.buildings.map(b => [b.id, b]));
      buildingObjs.forEach(b => {
        const bs = stateBMap.get(b.id);
        b.targetY = 0;
        b.currentY = 0;
        b.recoil = 0;
        b.group.position.y = 0;
        b.bodyMesh.scale.y = 1;
        if (bs) b.group.position.set(bs.x, 0, bs.z);
      });
    },

    dispose() {
      container.removeEventListener('resident-presence', onResidentPresence);
      container.removeEventListener('resident-visible', onResidentVisibility);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      residents.dispose();
      container.removeEventListener('world-focus', onWorldFocus);
      controls.removeEventListener('start', cancelFocus);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      resizeObserver.disconnect();
      controls.dispose();

      if (routeGroup) {
        scene.remove(routeGroup);
        routeGroup.traverse(c => {
          if (c instanceof THREE.Mesh) {
            c.geometry.dispose();
            (c.material as THREE.Material).dispose();
          }
        });
      }

      activeChar.dispose();
      debrisGeo.dispose();
      ringWaveGeo.dispose();
      scene.traverse(c => {
        if (c instanceof THREE.Mesh) {
          c.geometry.dispose();
          const mats = Array.isArray(c.material) ? c.material : [c.material];
          mats.forEach(m => {
            if (m) {
              if ('map' in m && m.map) m.map.dispose();
              m.dispose();
            }
          });
        }
      });
      renderer.dispose();
      if (renderer.domElement.parentElement) {
        renderer.domElement.parentElement.removeChild(renderer.domElement);
      }
    }
  };
}
