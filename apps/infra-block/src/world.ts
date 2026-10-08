import { createBrandMarkers, type BrandTenant } from './brand-atlas';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Layer, InfraNode, GameState, WorldEvent, WorldController, CharacterId } from './contracts';
import { createCharacter, CharacterInstance } from './characters';
import { RESIDENTS, type ResidentPresence } from './residents';
import { createResidentCrew } from './resident-characters';
import { createArchitecture } from './architecture';
import { createEnvironment } from './environment';
import { renderBudget, type GraphicsProfile } from './render-budget';
import { createArchipelago, fitCameraDistance } from './archipelago';
import { FLEET_LAYOUT, fleetNodes, type FleetProjection } from './fleet-model';

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
  scene.background = new THREE.Color('#d8e2df');
  scene.fog = new THREE.Fog('#d8e2df', 150, 950);

  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 50000);
  camera.position.set(35, 37, 41);

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'default' });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  let graphicsProfile: GraphicsProfile = 'balanced';
  let graphicsBudget = renderBudget(graphicsProfile, window.devicePixelRatio);
  renderer.setPixelRatio(graphicsBudget.pixelRatio);
  renderer.domElement.dataset.graphicsProfile = graphicsProfile;
  let lastRenderAt = -Infinity;
  renderer.info.autoReset = false;
  let lastMetricsAt = 0;
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
  let fittedIslandDistance = 350;
  let islandOverview = true;
  let followSuspended = false;
  let overlayWasOpen = false;
  const hasOverlay = () => ['field-kit-open', 'source-notes-open', 'home-encounter-open'].some(name => document.body.classList.contains(name)) || Boolean(document.querySelector('dialog[open]'));
  const onWorldFocus = (event: Event) => {
    const id = (event as CustomEvent<string | null>).detail;
    if (worldView === 'archipelago') {
      // Overlay close/focus events must not restore a local crew camera while
      // charting. Clearing focus leaves logical pan and chart orbit intact.
      focusTarget = null; focusDistance = null; focusDirection = null;
      return;
    }
    const controlled = residents.controlState();
    islandOverview = !id && !controlled.slug && residentsEnabled;
    if (islandOverview) fittedIslandDistance = fitWholeIsland();
    else camera.clearViewOffset();
    scene.fog = islandOverview
      ? new THREE.Fog('#d8e2df', Math.max(150, fittedIslandDistance * 1.2), Math.max(950, fittedIslandDistance * 3))
      : new THREE.Fog('#d8e2df', 150, 950);
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
    controls.minDistance = station ? 24 : islandOverview ? Math.max(fittedMinDistance, fittedIslandDistance * 0.5) : fittedMinDistance;
    controls.maxDistance = (islandOverview ? fittedIslandDistance : fittedDistance) * 1.7;
    focusDistance = station ? 36 : islandOverview ? fittedIslandDistance : fittedDistance;
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
  dirLight.shadow.mapSize.width = graphicsBudget.shadowSize;
  dirLight.shadow.mapSize.height = graphicsBudget.shadowSize;
  dirLight.shadow.bias = -0.0003;
  dirLight.shadow.camera.near = 10;
  dirLight.shadow.camera.far = 140;
  const d = 34;
  dirLight.shadow.camera.left = -d;
  dirLight.shadow.camera.right = d;
  dirLight.shadow.camera.top = d;
  dirLight.shadow.camera.bottom = -d;
  scene.add(dirLight);

  // One detailed town retains its local crew, collision and gameplay coordinates.
  const townRoot = new THREE.Group(); townRoot.name = 'DetailedTown'; scene.add(townRoot);
  const environment = createEnvironment(initialState.seed); townRoot.add(environment);
  const archipelago = createArchipelago(initialState.seed, FLEET_LAYOUT); scene.add(archipelago.group);
  let islandId: string = FLEET_LAYOUT[0].id;
  let worldView: 'town' | 'archipelago' = 'town';
  let logicalX = FLEET_LAYOUT[0].x, logicalZ = FLEET_LAYOUT[0].z;
  const islandLabels = document.createElement('div'); islandLabels.className = 'sg-world-island-labels';
  Object.assign(islandLabels.style, { position: 'absolute', inset: '0', pointerEvents: 'none', overflow: 'hidden' });
  container.appendChild(islandLabels);
  const labelButtons = FLEET_LAYOUT.map(slot => {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.island = slot.id;
    button.textContent = slot.name; button.title = `${slot.name} — visit island`;
    Object.assign(button.style, { position: 'absolute', pointerEvents: 'auto', border: '2px solid #37514b', borderRadius: '12px', color: '#233f38', background: '#f4efd9', boxShadow: '0 3px 0 #39574c55', padding: '5px 10px', font: '700 13px "Barlow Condensed", sans-serif', whiteSpace: 'nowrap', transform: 'translate(-50%, -100%)' });
    button.addEventListener('click', () => {
      if (!residentsEnabled || hasOverlay()) return;
      // Travel flows through the same root-owned input and accessibility guard
      // as the atlas and Fleet pane rather than calling the world directly.
      container.dispatchEvent(new CustomEvent('fleet-visit', { bubbles: true, detail: { id: slot.id } }));
    });
    islandLabels.appendChild(button); return button;
  });
  function synchronizeWorld() {
    const selected = FLEET_LAYOUT.find(slot => slot.id === islandId)!;
    const dx = selected.x - logicalX, dz = selected.z - logicalZ;
    townRoot.visible = Math.hypot(dx, dz) < 1600;
    townRoot.position.set(townRoot.visible ? dx : 0, 0, townRoot.visible ? dz : 0);
    archipelago.anchor(logicalX, logicalZ, islandId);
    const stats = archipelago.stats();
    Object.assign(renderer.domElement.dataset, {
      fleetIsland: islandId, worldView, worldX: String(logicalX), worldZ: String(logicalZ),
      sceneryChunks: String(stats.chunks), archipelagoCalls: String(stats.drawCalls),
      archipelagoTriangles: String(stats.triangles), environmentTriangles: String(environment.userData.environmentalStats.triangles), detailedTowns: '1'
    });
  }
  function selectionEvent() {
    container.dispatchEvent(new CustomEvent('fleet-selection', { bubbles: true, detail: { id: islandId, view: worldView } }));
  }
  function frameInsets() {
    const rect = container.getBoundingClientRect();
    const width = Math.max(1, rect.width), height = Math.max(1, rect.height);
    let top = 16, bottom = 16;
    for (const selector of ['.sg-header', '#sg-fleet-atlas', '.ih-mission-strip']) {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element || !element.getClientRects().length) continue;
      top = Math.max(top, element.getBoundingClientRect().bottom - rect.top + 16);
    }
    const lowerSelectors = width < 768 ? ['.ih-belt-wrap', '.ih-touch-pad', '.ih-walk-hud'] : ['.ih-belt-wrap'];
    for (const selector of lowerSelectors) {
      const element = document.querySelector<HTMLElement>(selector);
      if (!element || !element.getClientRects().length) continue;
      bottom = Math.max(bottom, rect.bottom - element.getBoundingClientRect().top + 16);
    }
    top = Math.min(top, height * 0.64);
    bottom = Math.min(bottom, Math.max(16, height - top - 90));
    // Moving the optical center leaves the coast in the available screen band.
    camera.setViewOffset(width, height, 0, (bottom - top) / 2, width, height);
    return { top: 1 - top / height * 2, bottom: -1 + bottom / height * 2, horizontal: 0.91 };
  }
  function fitWholeIsland() {
    return fitCameraDistance(camera, new THREE.Box3(new THREE.Vector3(-85, -8, -85), new THREE.Vector3(85, 16, 90)), townDirection, new THREE.Vector3(0, 3, 0), 240, frameInsets());
  }
  function frameTown(overview: boolean) {
    islandOverview = overview;
    if (overview) fittedIslandDistance = fitWholeIsland();
    else camera.clearViewOffset();
    const distance = overview ? fittedIslandDistance : fittedDistance;
    scene.fog = overview
      ? new THREE.Fog('#d8e2df', Math.max(150, distance * 1.2), Math.max(950, distance * 3))
      : new THREE.Fog('#d8e2df', 150, 950);
    controls.target.set(0, 3, 0); camera.position.copy(controls.target).addScaledVector(townDirection, distance);
    controls.minDistance = overview ? Math.max(fittedMinDistance, distance * 0.5) : fittedMinDistance;
    controls.maxDistance = distance * 1.7;
    camera.lookAt(controls.target); controls.update();
  }
  function frameChart() {
    const limits = frameInsets();
    const direction = new THREE.Vector3(0.42, 0.82, 0.4).normalize();
    const centerZ = (FLEET_LAYOUT[0].z + FLEET_LAYOUT[2].z) / 2;
    const bounds = new THREE.Box3(new THREE.Vector3(-265, -8, -110 - centerZ - 90), new THREE.Vector3(265, 22, 180 - centerZ + 90));
    const distance = fitCameraDistance(camera, bounds, direction, new THREE.Vector3(), 1350, limits);
    controls.target.set(0, 0, 0); camera.position.copy(controls.target).addScaledVector(direction, distance);
    controls.minDistance = distance * 0.6; controls.maxDistance = distance * 2;
    scene.fog = new THREE.Fog('#d8e2df', Math.max(1400, distance * 1.3), Math.max(3500, distance * 4));
    camera.lookAt(controls.target); controls.update();
  }
  function setWorldView(view: 'town' | 'archipelago') {
    worldView = view === 'archipelago' ? 'archipelago' : 'town';
    focusTarget = null; focusDistance = null; focusDirection = null; followSuspended = false;
    if (worldView === 'archipelago') {
      logicalX = (FLEET_LAYOUT[0].x + FLEET_LAYOUT[1].x) / 2;
      logicalZ = (FLEET_LAYOUT[0].z + FLEET_LAYOUT[2].z) / 2;
      scene.fog = new THREE.Fog('#d8e2df', 1400, 3500); frameChart();
    } else {
      const selected = FLEET_LAYOUT.find(slot => slot.id === islandId)!;
      logicalX = selected.x; logicalZ = selected.z;
      scene.fog = new THREE.Fog('#d8e2df', 150, 950);
      frameTown(residentsEnabled && !residents.controlState().slug);
    }
    synchronizeWorld(); selectionEvent(); lastRenderAt = -Infinity;
  }
  function visitIsland(id: string) {
    if (!FLEET_LAYOUT.some(slot => slot.id === id)) return;
    islandId = id; setWorldView('town');
  }
  synchronizeWorld();

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
  townRoot.add(buildingGroup);

  initialState.buildings.forEach((bs, bIdx) => {
    const node = nodeMap.get(bs.id);
    const bGroup = new THREE.Group();
    bGroup.position.set(bs.x, 0, bs.z);
    bGroup.userData = { id: bs.id };

    const { bodyMesh, materials: mats } = createArchitecture(bs, node, bIdx);
    bGroup.add(bodyMesh);

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

  const tenantStation = buildingObjs.find(item => item.id === 'tenant-vault');
  const brandMarkers = createBrandMarkers(tenantStation?.group.position.clone() ?? new THREE.Vector3(), slug => container.dispatchEvent(new CustomEvent('brand-select', {detail:{slug}})));
  townRoot.add(brandMarkers.group);
  const onBrandMarkers = (event: Event) => {
    const {tenants,mode,stale} = (event as CustomEvent<{tenants:BrandTenant[]|null;mode:string;stale:boolean}>).detail;
    brandMarkers.update(tenants,mode,stale);
    renderer.domElement.dataset.brandCount = String(brandMarkers.group.children.length);
  };
  container.addEventListener('brand-markers', onBrandMarkers);
  const focusBrands = () => {
    if (worldView === 'archipelago') setWorldView('town');
    followSuspended = true;
    controls.minDistance = 18;
    focusDistance = 30;
    focusDirection = new THREE.Vector3(14, 34, 16).normalize();
    focusTarget = brandMarkers.group.position.clone().add(new THREE.Vector3(0, 1.8, 0));
  };
  container.addEventListener('brand-focus', focusBrands);

  // Selection Ring
  const ringGeo = new THREE.RingGeometry(2.6, 3.2, 32);
  ringGeo.rotateX(-Math.PI / 2);
  const ringMat = new THREE.MeshBasicMaterial({ color: '#ffcc00', side: THREE.DoubleSide });
  const selectRing = new THREE.Mesh(ringGeo, ringMat);
  selectRing.position.y = 0.06;
  selectRing.visible = false;
  townRoot.add(selectRing);

  // Cars
  interface CarObj {
    id: number;
    group: THREE.Group;
    body: THREE.Mesh;
  }
  const carGroup = new THREE.Group();
  townRoot.add(carGroup);
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
  townRoot.add(activeChar.group);
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
  townRoot.add(residents.group);
  let residentsEnabled = true;
  const onResidentPresence = (event: Event) => {
    const presence = (event as CustomEvent<ResidentPresence[]>).detail;
    if (Array.isArray(presence)) residents.setPresence(presence);
  };
  const onResidentVisibility = (event: Event) => {
    residentsEnabled = (event as CustomEvent<boolean>).detail === true;
    if (!residentsEnabled) {
      residents.group.visible = false;
      if (worldView === 'town') frameTown(false);
    }
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
    if (Math.hypot(dx, dy) > 5 || worldView === 'archipelago') return;

    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(pointer, camera);
    const brandObstruction = raycaster.intersectObjects(buildingGroup.children, true)[0];
    if (brandMarkers.pick(raycaster, brandObstruction?.distance ?? Infinity)) return;
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
    renderer.domElement.style.cursor = worldView === 'town' && pickResident() ? 'pointer' : 'grab';
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
      const fitCamera = camera.clone(); fitCamera.clearViewOffset();
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
      if (worldView === 'archipelago') { frameChart(); return; }
      if (islandOverview && !controlled.slug) {
        fittedIslandDistance = fitWholeIsland();
        if (focusTarget) focusDistance = fittedIslandDistance;
        else frameTown(true);
      } else {
        camera.clearViewOffset();
        if (!controlled.slug && !focusTarget) camera.position.copy(controls.target).addScaledVector(townDirection, distance);
        controls.minDistance = controlled.slug ? 18 : focusDistance === 36 ? 24 : fittedMinDistance;
        controls.maxDistance = distance * 1.7;
      }
    }
  });
  resizeObserver.observe(container);

  // Return Controller
  return {
    setFleet(projection: FleetProjection) {
      const assigned = fleetNodes(projection.snapshot);
      for (const button of labelButtons) {
        const node = assigned.find(node => node.id === button.dataset.island);
        const slot = FLEET_LAYOUT.find(slot => slot.id === button.dataset.island)!;
        button.textContent = `${slot.name} · ${node?.assignment ?? 'planned'}`;
        button.title = `${slot.name} — ${node?.assignment ?? 'planned'} device assignment; visit island`;
      }
    },
    visitIsland, setWorldView,
    controlResident(slug: string | null) {
      if (slug && worldView === 'archipelago') setWorldView('town');
      residents.controlResident(slug);
      if (worldView === 'archipelago') return;
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
      if (worldView === 'archipelago') {
        const panX = Number.isFinite(x) ? x : 0, panZ = Number.isFinite(z) ? z : 0;
        if ((panX || panZ) && !hasOverlay() && Number.isFinite(dt)) {
          const step = 180 * Math.max(0, Math.min(dt, 0.1));
          const length = Math.max(1, Math.hypot(panX, panZ));
          logicalX += panX / length * step; logicalZ += panZ / length * step; synchronizeWorld();
        }
        return { slug: null, x: logicalX, z: logicalZ, moving: Boolean(panX || panZ) && !hasOverlay(), nearbySlug: null };
      }
      if ((x || z) && followSuspended && !hasOverlay()) onWorldFocus(new CustomEvent('world-focus', { detail: null }));
      const forward = camera.getWorldDirection(new THREE.Vector3());
      return residents.moveResident({ x, z: -z }, { x: forward.x, z: forward.z }, dt);
    },
    update(state: GameState, dt: number) {
      if (state.mode === 'playing' && worldView === 'archipelago') setWorldView('town');
      residents.update(dt, residentsEnabled ? state.mode : 'playing');
      brandMarkers.group.visible = residentsEnabled;
      if (!residentsEnabled) residents.group.visible = false;
      const controlled = residents.controlState();
      const overlayOpen = hasOverlay();
      if (controlled.slug && overlayWasOpen && !overlayOpen) onWorldFocus(new CustomEvent('world-focus', { detail: null }));
      overlayWasOpen = overlayOpen;
      const followAllowed = Boolean(worldView === 'town' && controlled.slug && !overlayOpen && !followSuspended);
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
        townRoot.remove(activeChar.group);
        activeChar.dispose();
        currentCharId = state.character;
        activeChar = createCharacter(currentCharId);
        townRoot.add(activeChar.group);
      }

      // Player Animation
      const moved = Math.hypot(state.player.x - prevPlayerPos.x, state.player.z - prevPlayerPos.z) > 0.001;
      prevPlayerPos = { x: state.player.x, z: state.player.z };
      activeChar.group.visible = true;
      const visualPlayer = state.mode === 'explore' ? { x: 0, z: 20.8, angle: 0.25 } : state.player;
      activeChar.group.scale.setScalar(state.mode === 'explore' ? 1.8 : 1.5);
      activeChar.animate(reducedMotion ? 0 : dt, visualPlayer, state.mode === 'playing' && !reducedMotion && moved);

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
          townRoot.remove(p.mesh);
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
          townRoot.remove(r.mesh);
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

      for (const button of labelButtons) {
        const point = archipelago.islandPosition(button.dataset.island!)!.project(camera);
        const visible = residentsEnabled && !overlayOpen && point.z >= -1 && point.z <= 1 && Math.abs(point.x) < 0.94 && Math.abs(point.y) < 0.94 && (worldView === 'archipelago' || button.dataset.island !== islandId);
        button.hidden = !visible;
        button.style.left = `${(point.x + 1) * 50}%`; button.style.top = `${(1 - point.y) * 50}%`;
      }
      const renderStarted = performance.now();
      if (document.hidden || renderStarted - lastRenderAt < 1000 / graphicsBudget.maxFps - 1) return;
      lastRenderAt = renderStarted;
      renderer.info.reset();
      renderer.render(scene, camera);
      if (renderStarted - lastMetricsAt >= 500) {
        lastMetricsAt = renderStarted;
        renderer.domElement.dataset.brandMarkers = JSON.stringify(brandMarkers.group.children.map(mesh => {
          const point = mesh.getWorldPosition(new THREE.Vector3()).project(camera);
          return {slug:mesh.userData.slug,x:(point.x+1)/2,y:(1-point.y)/2,visible:point.z>=-1&&point.z<=1&&Math.abs(point.x)<=1&&Math.abs(point.y)<=1};
        }));
        Object.assign(renderer.domElement.dataset, {
          renderCalls: String(renderer.info.render.calls),
          renderTriangles: String(renderer.info.render.triangles),
          renderGeometries: String(renderer.info.memory.geometries),
          renderTextures: String(renderer.info.memory.textures),
          renderPixelRatio: String(renderer.getPixelRatio()),
          renderCpuMs: (performance.now() - renderStarted).toFixed(2),
          graphicsProfile,
          renderFpsCap: String(graphicsBudget.maxFps),
          renderShadows: String(renderer.shadowMap.enabled),
          renderShadowSize: String(graphicsBudget.shadowSize)
        });
      }
    },

    setGraphics(profile: GraphicsProfile) {
      graphicsProfile = profile === 'eco' ? 'eco' : 'balanced';
      graphicsBudget = renderBudget(graphicsProfile, window.devicePixelRatio);
      renderer.setPixelRatio(graphicsBudget.pixelRatio);
      const shadowsChanged = renderer.shadowMap.enabled !== graphicsBudget.shadows;
      renderer.shadowMap.enabled = graphicsBudget.shadows;
      renderer.shadowMap.needsUpdate = true;
      if (shadowsChanged) {
        const materials = new Set<THREE.Material>();
        scene.traverse(object => {
          if (!(object instanceof THREE.Mesh)) return;
          for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
            if (!materials.has(material)) { materials.add(material); material.needsUpdate = true; }
          }
        });
      }
      renderer.domElement.dataset.graphicsProfile = graphicsProfile;
      lastRenderAt = -Infinity;
      lastMetricsAt = 0;
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
          townRoot.add(rm);
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
          townRoot.add(pMesh);
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
          if (m.transparent !== (alpha < 1.0)) m.needsUpdate = true;
          m.transparent = alpha < 1.0;
          m.opacity = alpha;
          m.depthWrite = alpha >= 0.99;
        });
      });
    },

    route(ids: string[]) {
      if (routeGroup) {
        townRoot.remove(routeGroup);
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
      townRoot.add(routeGroup);
    },

    reset(state: GameState) {
      this.filter('all');
      this.select(null);
      this.route([]);

      debrisList.forEach(p => {
        townRoot.remove(p.mesh);
        (p.mesh.material as THREE.Material).dispose();
      });
      debrisList.length = 0;

      ringList.forEach(r => {
        townRoot.remove(r.mesh);
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
      islandLabels.remove(); scene.remove(archipelago.group); archipelago.dispose();
      container.removeEventListener('brand-markers', onBrandMarkers);
      container.removeEventListener('brand-focus', focusBrands);
      brandMarkers.dispose();
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
      dirLight.shadow.map?.dispose();
      dirLight.shadow.mapPass?.dispose();

      if (routeGroup) {
        townRoot.remove(routeGroup);
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
      const disposedGeometries = new Set<THREE.BufferGeometry>();
      const disposedMaterials = new Set<THREE.Material>();
      const disposedTextures = new Set<THREE.Texture>();
      scene.traverse(c => {
        if (c instanceof THREE.InstancedMesh) c.dispose();
        if (c instanceof THREE.Mesh) {
          if (!disposedGeometries.has(c.geometry)) { disposedGeometries.add(c.geometry); c.geometry.dispose(); }
          const mats = Array.isArray(c.material) ? c.material : [c.material];
          mats.forEach(m => {
            if (m) {
              if ('map' in m && m.map instanceof THREE.Texture && !disposedTextures.has(m.map)) { disposedTextures.add(m.map); m.map.dispose(); }
              if (!disposedMaterials.has(m)) { disposedMaterials.add(m); m.dispose(); }
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
