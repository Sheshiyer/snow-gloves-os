import * as THREE from 'three';
import type { BuildingState, InfraNode } from './contracts';

const FACADE_STYLES = ['brick', 'plaster', 'timber', 'metal'] as const;

function blendColor(hexStr: string, baseR: number, baseG: number, baseB: number, tintFactor: number): string {
  let c = 0x888888;
  if (hexStr && hexStr.startsWith('#')) {
    c = parseInt(hexStr.slice(1), 16) || c;
  }
  const r = (c >> 16) & 255;
  const g = (c >> 8) & 255;
  const b = c & 255;
  const nr = Math.round(baseR * (1 - tintFactor) + r * tintFactor);
  const ng = Math.round(baseG * (1 - tintFactor) + g * tintFactor);
  const nb = Math.round(baseB * (1 - tintFactor) + b * tintFactor);
  return `rgb(${nr},${ng},${nb})`;
}

function createBuildingAtlas(node: InfraNode | undefined, styleIdx: number, floors: number): THREE.CanvasTexture | null {
  if (typeof document === 'undefined' || !document.createElement) return null;
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const tintHex = node?.color || '#888888';
  const style = FACADE_STYLES[Math.abs(styleIdx) % FACADE_STYLES.length];
  const baseCols = {
    brick: [165, 120, 100],
    plaster: [210, 205, 195],
    timber: [140, 115, 90],
    metal: [120, 130, 135]
  }[style];
  const wallColor = blendColor(tintHex, baseCols[0], baseCols[1], baseCols[2], 0.12);
  const trimColor = blendColor(tintHex, 60, 60, 65, 0.2);
  const winGlass = 'rgb(45, 55, 65)';
  const winFrame = 'rgb(220, 215, 205)';

  // Tile quadrants: 0:Front(top-left), 1:Back(top-right), 2:Left(bottom-left), 3:Right(bottom-right)
  for (let q = 0; q < 4; q++) {
    const ox = (q % 2) * 256;
    const oy = Math.floor(q / 2) * 256;
    ctx.fillStyle = wallColor;
    ctx.fillRect(ox, oy, 256, 256);

    // Masonry / pattern courses
    ctx.strokeStyle = 'rgba(0,0,0,0.08)';
    ctx.lineWidth = 1;
    if (style === 'brick') {
      for (let y = 8; y < 256; y += 10) {
        ctx.beginPath(); ctx.moveTo(ox, oy + y); ctx.lineTo(ox + 256, oy + y); ctx.stroke();
        for (let x = ((y / 10) % 2 ? 8 : 20); x < 256; x += 24) {
          ctx.beginPath(); ctx.moveTo(ox + x, oy + y); ctx.lineTo(ox + x, oy + Math.min(y + 10, 256)); ctx.stroke();
        }
      }
    } else if (style === 'timber') {
      for (let x = 32; x < 256; x += 32) {
        ctx.beginPath(); ctx.moveTo(ox + x, oy); ctx.lineTo(ox + x, oy + 256); ctx.stroke();
      }
    } else if (style === 'metal') {
      for (let y = 16; y < 256; y += 16) {
        ctx.beginPath(); ctx.moveTo(ox, oy + y); ctx.lineTo(ox + 256, oy + y); ctx.stroke();
      }
    }

    // Plinth at bottom of elevation
    ctx.fillStyle = trimColor;
    ctx.fillRect(ox, oy + 240, 256, 16);

    const cols = 3;
    const rowCount = Math.min(5, Math.max(1, floors));
    const isFront = (q === 0);

    // Windows grid
    for (let r = 0; r < rowCount; r++) {
      const isGround = (r === 0);
      const wy = oy + 240 - (r + 1) * Math.floor(220 / (rowCount + 1));
      for (let c = 0; c < cols; c++) {
        const wx = ox + 32 + c * 70;
        if (isFront && isGround && c === 1) {
          // Entrance Door on front ground
          ctx.fillStyle = 'rgb(35, 30, 28)';
          ctx.fillRect(wx - 4, oy + 195, 44, 45);
          ctx.fillStyle = trimColor;
          ctx.fillRect(wx - 6, oy + 188, 48, 7); // Lintel
          const label = (node?.short || node?.name || 'ENTRANCE').substring(0, 8);
          ctx.fillStyle = 'rgb(240, 230, 200)';
          ctx.font = 'bold 9px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(label, wx + 18, oy + 185);
        } else {
          // Standard Window
          ctx.fillStyle = 'rgba(0,0,0,0.2)';
          ctx.fillRect(wx - 2, wy - 2, 34, 30); // Shade/recess
          ctx.fillStyle = winFrame;
          ctx.fillRect(wx, wy, 30, 26);
          ctx.fillStyle = winGlass;
          ctx.fillRect(wx + 2, wy + 2, 26, 22);
          ctx.strokeStyle = winFrame;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(wx + 15, wy + 2); ctx.lineTo(wx + 15, wy + 24); // Mullion
          ctx.moveTo(wx + 2, wy + 13); ctx.lineTo(wx + 28, wy + 13); // Transom
          ctx.stroke();
          ctx.fillStyle = trimColor;
          ctx.fillRect(wx - 2, wy - 4, 34, 3); // Lintel
          ctx.fillRect(wx - 3, wy + 26, 36, 3); // Sill
        }
      }
    }
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}

function applyElevationUVs(geom: THREE.BoxGeometry) {
  const uvAttr = geom.getAttribute('uv');
  // Box faces order: 0:+X(Right), 1:-X(Left), 2:+Y(Top), 3:-Y(Bottom), 4:+Z(Front), 5:-Z(Back)
  // UV Atlas layout (0..1):
  // Front (q=0): u: 0..0.5, v: 0.5..1.0
  // Back  (q=1): u: 0.5..1, v: 0.5..1.0
  // Left  (q=2): u: 0..0.5, v: 0.0..0.5
  // Right (q=3): u: 0.5..1, v: 0.0..0.5
  const tiles: Record<number, [number, number, number, number]> = {
    4: [0.0, 0.5, 0.5, 1.0], // Front (+Z)
    5: [0.5, 1.0, 0.5, 1.0], // Back (-Z)
    1: [0.0, 0.5, 0.0, 0.5], // Left (-X)
    0: [0.5, 1.0, 0.0, 0.5], // Right (+X)
  };

  for (let face = 0; face < 6; face++) {
    const tile = tiles[face];
    if (tile) {
      const [u0, u1, v0, v1] = tile;
      const vIdx = face * 4;
      uvAttr.setXY(vIdx + 0, u0, v1);
      uvAttr.setXY(vIdx + 1, u1, v1);
      uvAttr.setXY(vIdx + 2, u0, v0);
      uvAttr.setXY(vIdx + 3, u1, v0);
    }
  }
  uvAttr.needsUpdate = true;
}

export function createArchitecture(
  bs: BuildingState,
  node: InfraNode | undefined,
  index: number
): { bodyMesh: THREE.Mesh; materials: THREE.Material[] } {
  const roofType = Math.abs(index) % 4;
  const w = bs.width;
  const d = bs.depth;
  const h = bs.height;

  const roofHeight = roofType === 2 ? Math.min(h * 0.12, 0.4) : Math.min(h * 0.28, Math.min(w, d) * 0.45);
  const wallH = Math.max(0.1, h - roofHeight);

  const wallGeom = new THREE.BoxGeometry(w, wallH, d);
  wallGeom.translate(0, -roofHeight / 2, 0);
  applyElevationUVs(wallGeom);

  const atlasTexture = createBuildingAtlas(node, index, bs.floors || 2);
  const wallMat = new THREE.MeshStandardMaterial({
    color: atlasTexture ? 0xffffff : '#c4bbaa',
    roughness: 0.85,
    metalness: 0.05,
    map: atlasTexture || null,
  });

  const plainRoofMat = new THREE.MeshStandardMaterial({
    color: blendColor(node?.color || '#555555', 70, 75, 80, 0.15),
    roughness: 0.9,
    metalness: 0.08,
    side: THREE.DoubleSide,
  });

  const trimMat = new THREE.MeshStandardMaterial({
    color: blendColor(node?.color || '#444444', 45, 48, 52, 0.18),
    roughness: 0.88,
    metalness: 0.05,
  });

  const materials: THREE.Material[] = [wallMat, plainRoofMat, trimMat];

  // Translate body downward by roofHeight/2 so local y bounds of body are [-roofHeight - wallH/2, wallH/2]
  // When bodyMesh is at world y = bs.height/2, bottom = h/2 - roofHeight/2 - wallH/2 = h/2 - h/2 = 0.
  const bodyMesh = new THREE.Mesh(wallGeom, wallMat);
  bodyMesh.name = `building_${bs.id}_body`;
  bodyMesh.position.set(0, h / 2, 0);

  const roofTopY = h / 2 - roofHeight;
  const hw = w / 2;
  const hd = d / 2;

  if (roofType === 0) {
    // Gable Pitched Roof
    const geom = new THREE.BufferGeometry();
    const positions = new Float32Array([
      // Left slope
      -hw, roofTopY, -hd,   0, roofTopY + roofHeight, -hd,   0, roofTopY + roofHeight,  hd,
      -hw, roofTopY, -hd,   0, roofTopY + roofHeight,  hd, -hw, roofTopY,  hd,
      // Right slope
        0, roofTopY + roofHeight, -hd,  hw, roofTopY, -hd,  hw, roofTopY,  hd,
        0, roofTopY + roofHeight, -hd,  hw, roofTopY,  hd,   0, roofTopY + roofHeight,  hd,
      // Front gable
      -hw, roofTopY,  hd,   0, roofTopY + roofHeight,  hd,  hw, roofTopY,  hd,
      // Back gable
       hw, roofTopY, -hd,   0, roofTopY + roofHeight, -hd, -hw, roofTopY, -hd,
    ]);
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.computeVertexNormals();
    const roofMesh = new THREE.Mesh(geom, plainRoofMat);
    roofMesh.name = 'roof_gable';
    bodyMesh.add(roofMesh);
  } else if (roofType === 1) {
    // Mono-pitch metal roof wedge (sloping along Z)
    const geom = new THREE.BufferGeometry();
    const positions = new Float32Array([
      // Top sloped face
      -hw, roofTopY, -hd,   hw, roofTopY, -hd,   hw, roofTopY + roofHeight, hd,
      -hw, roofTopY, -hd,   hw, roofTopY + roofHeight, hd,  -hw, roofTopY + roofHeight, hd,
      // Front vertical
      -hw, roofTopY,  hd,   hw, roofTopY,  hd,   hw, roofTopY + roofHeight, hd,
      -hw, roofTopY,  hd,   hw, roofTopY + roofHeight, hd,  -hw, roofTopY + roofHeight, hd,
      // Left triangular side
      -hw, roofTopY, -hd,  -hw, roofTopY + roofHeight, hd,  -hw, roofTopY, hd,
      // Right triangular side
       hw, roofTopY, -hd,   hw, roofTopY, hd,   hw, roofTopY + roofHeight, hd,
    ]);
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.computeVertexNormals();
    const roofMesh = new THREE.Mesh(geom, plainRoofMat);
    roofMesh.name = 'roof_monopitch';
    bodyMesh.add(roofMesh);
  } else if (roofType === 2) {
    // Flat Roof with 4 parapet pieces and deck slab
    const parapetH = Math.min(roofHeight, 0.4);
    const parapetThick = Math.min(w * 0.08, d * 0.08, 0.25);
    const slabGeom = new THREE.BoxGeometry(w, 0.08, d);
    const slabMesh = new THREE.Mesh(slabGeom, plainRoofMat);
    slabMesh.name = 'roof_flat_slab';
    slabMesh.position.set(0, roofTopY + 0.04, 0);
    bodyMesh.add(slabMesh);

    const fGeom = new THREE.BoxGeometry(w, parapetH, parapetThick);
    const sGeom = new THREE.BoxGeometry(parapetThick, parapetH, Math.max(0.1, d - parapetThick * 2));
    const py = roofTopY + parapetH / 2;

    const pFront = new THREE.Mesh(fGeom, trimMat);
    pFront.name = 'roof_parapet_f';
    pFront.position.set(0, py, hd - parapetThick / 2);
    const pBack = new THREE.Mesh(fGeom, trimMat);
    pBack.name = 'roof_parapet_b';
    pBack.position.set(0, py, -hd + parapetThick / 2);
    const pLeft = new THREE.Mesh(sGeom, trimMat);
    pLeft.name = 'roof_parapet_l';
    pLeft.position.set(-hw + parapetThick / 2, py, 0);
    const pRight = new THREE.Mesh(sGeom, trimMat);
    pRight.name = 'roof_parapet_r';
    pRight.position.set(hw - parapetThick / 2, py, 0);

    bodyMesh.add(pFront, pBack, pLeft, pRight);
  } else {
    // Hipped Roof apex triangles
    const geom = new THREE.BufferGeometry();
    const apexY = roofTopY + roofHeight;
    const positions = new Float32Array([
      // Front
      -hw, roofTopY,  hd,  hw, roofTopY,  hd,  0, apexY, 0,
      // Back
       hw, roofTopY, -hd, -hw, roofTopY, -hd,  0, apexY, 0,
      // Left
      -hw, roofTopY, -hd, -hw, roofTopY,  hd,  0, apexY, 0,
      // Right
       hw, roofTopY,  hd,  hw, roofTopY, -hd,  0, apexY, 0,
    ]);
    geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geom.computeVertexNormals();
    const roofMesh = new THREE.Mesh(geom, plainRoofMat);
    roofMesh.name = 'roof_hipped';
    bodyMesh.add(roofMesh);
  }

  // Base plinth strip
  const plinthH = Math.min(0.2, wallH * 0.08);
  const plinthGeom = new THREE.BoxGeometry(w, plinthH, d);
  const plinthMesh = new THREE.Mesh(plinthGeom, trimMat);
  plinthMesh.name = 'plinth';
  plinthMesh.position.set(0, -h / 2 + plinthH / 2, 0);
  bodyMesh.add(plinthMesh);

  bodyMesh.traverse(object => {
    if (object instanceof THREE.Mesh) { object.castShadow = true; object.receiveShadow = true; }
  });
  return { bodyMesh, materials };
}

