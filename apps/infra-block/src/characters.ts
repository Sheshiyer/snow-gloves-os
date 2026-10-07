import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { CharacterId, GameState } from './contracts';

export interface CharacterInstance {
  group: THREE.Group;
  animate: (dt: number, player: GameState['player'], moving: boolean) => void;
  dispose: () => void;
}

export function createCharacter(id: CharacterId): CharacterInstance {
  const group = new THREE.Group();
  const cleanups: (() => void)[] = [];

  const makeMat = (color: number | string, rough = 0.85) => {
    const m = new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0.05 });
    cleanups.push(() => m.dispose());
    return m;
  };
  const makeGeo = <T extends THREE.BufferGeometry>(geo: T): T => {
    cleanups.push(() => geo.dispose());
    return geo;
  };

  let leftLeg: THREE.Object3D | null = null;
  let rightLeg: THREE.Object3D | null = null;
  let leftArm: THREE.Object3D | null = null;
  let rightArm: THREE.Object3D | null = null;
  let tail: THREE.Object3D | null = null;
  let walkCycle = 0;

  if (id === 'munch') {
    // Lime cream dinosaur with orange back spikes & horns
    const limeMat = makeMat('#88cc55');
    const creamMat = makeMat('#fbf7e2');
    const orangeMat = makeMat('#ff8833');
    const darkMat = makeMat('#222222');

    const body = new THREE.Mesh(makeGeo(new THREE.CapsuleGeometry(0.7, 0.7, 8, 16)), limeMat);
    body.position.y = 1.1;
    group.add(body);

    const belly = new THREE.Mesh(makeGeo(new THREE.SphereGeometry(0.55, 12, 12)), creamMat);
    belly.scale.set(0.85, 1.1, 0.6);
    belly.position.set(0, 1.0, 0.45);
    group.add(belly);

    const snout = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.75, 0.5, 0.7, 3, 0.07)), limeMat);
    snout.position.set(0, 1.45, 0.65);
    group.add(snout);

    // Horns
    const hornGeo = makeGeo(new THREE.ConeGeometry(0.12, 0.35, 6));
    const hornL = new THREE.Mesh(hornGeo, creamMat);
    hornL.position.set(-0.25, 1.85, 0.2);
    hornL.rotation.x = -0.3;
    const hornR = new THREE.Mesh(hornGeo, creamMat);
    hornR.position.set(0.25, 1.85, 0.2);
    hornR.rotation.x = -0.3;
    group.add(hornL, hornR);

    // Eyes
    const eyeGeo = makeGeo(new THREE.SphereGeometry(0.09, 8, 8));
    const eyeL = new THREE.Mesh(eyeGeo, darkMat);
    eyeL.position.set(-0.32, 1.55, 0.75);
    const eyeR = new THREE.Mesh(eyeGeo, darkMat);
    eyeR.position.set(0.32, 1.55, 0.75);
    group.add(eyeL, eyeR);

    // Back spikes
    const spikeGeo = makeGeo(new THREE.ConeGeometry(0.12, 0.28, 5));
    for (let i = 0; i < 4; i++) {
      const sp = new THREE.Mesh(spikeGeo, orangeMat);
      sp.rotation.x = -Math.PI * 0.45;
      sp.position.set(0, 1.6 - i * 0.35, -0.65 - (i === 3 ? 0.2 : 0));
      group.add(sp);
    }

    // Tail
    const tailGroup = new THREE.Group();
    tailGroup.position.set(0, 0.7, -0.6);
    const tailMesh = new THREE.Mesh(makeGeo(new THREE.ConeGeometry(0.28, 1.1, 6)), limeMat);
    tailMesh.rotation.x = -Math.PI * 0.45;
    tailMesh.position.set(0, 0.1, -0.5);
    tailGroup.add(tailMesh);
    group.add(tailGroup);
    tail = tailGroup;

    // Legs
    const legGeo = makeGeo(new THREE.CylinderGeometry(0.22, 0.26, 0.65, 8));
    const legL = new THREE.Mesh(legGeo, limeMat);
    legL.position.set(-0.45, 0.35, 0);
    const legR = new THREE.Mesh(legGeo, limeMat);
    legR.position.set(0.45, 0.35, 0);
    group.add(legL, legR);
    leftLeg = legL;
    rightLeg = legR;

  } else if (id === 'bongo') {
    // Orange cream gorilla big fists brow rounded ears
    const orangeMat = makeMat('#f07c34');
    const creamMat = makeMat('#fceddb');
    const darkMat = makeMat('#2b201a');

    const torso = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(1.2, 1.1, 0.9, 3, 0.07)), orangeMat);
    torso.position.y = 1.15;
    group.add(torso);

    const chest = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.85, 0.75, 0.2, 3, 0.07)), creamMat);
    chest.position.set(0, 1.15, 0.45);
    group.add(chest);

    const head = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.75, 0.65, 0.65, 3, 0.07)), orangeMat);
    head.position.set(0, 1.85, 0.15);
    const brow = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.8, 0.18, 0.25, 3, 0.07)), orangeMat);
    brow.position.set(0, 1.95, 0.45);
    group.add(head, brow);

    const earGeo = makeGeo(new THREE.CylinderGeometry(0.14, 0.14, 0.08, 8));
    const earL = new THREE.Mesh(earGeo, creamMat);
    earL.rotation.z = Math.PI / 2;
    earL.position.set(-0.44, 1.85, 0.15);
    const earR = new THREE.Mesh(earGeo, creamMat);
    earR.rotation.z = Math.PI / 2;
    earR.position.set(0.44, 1.85, 0.15);
    group.add(earL, earR);

    const eyeGeo = makeGeo(new THREE.SphereGeometry(0.07, 6, 6));
    const eyeL = new THREE.Mesh(eyeGeo, darkMat);
    eyeL.position.set(-0.2, 1.82, 0.46);
    const eyeR = new THREE.Mesh(eyeGeo, darkMat);
    eyeR.position.set(0.2, 1.82, 0.46);
    group.add(eyeL, eyeR);

    const armGeo = makeGeo(new RoundedBoxGeometry(0.42, 0.9, 0.45, 3, 0.07));
    const fistGeo = makeGeo(new RoundedBoxGeometry(0.5, 0.45, 0.5, 3, 0.07));
    const armL = new THREE.Group();
    armL.position.set(-0.8, 1.35, 0.1);
    const armMeshL = new THREE.Mesh(armGeo, orangeMat);
    armMeshL.position.y = -0.3;
    const fistMeshL = new THREE.Mesh(fistGeo, creamMat);
    fistMeshL.position.y = -0.75;
    armL.add(armMeshL, fistMeshL);

    const armR = new THREE.Group();
    armR.position.set(0.8, 1.35, 0.1);
    const armMeshR = new THREE.Mesh(armGeo, orangeMat);
    armMeshR.position.y = -0.3;
    const fistMeshR = new THREE.Mesh(fistGeo, creamMat);
    fistMeshR.position.y = -0.75;
    armR.add(armMeshR, fistMeshR);
    group.add(armL, armR);
    leftArm = armL;
    rightArm = armR;

    const legGeo = makeGeo(new THREE.CylinderGeometry(0.25, 0.28, 0.6, 8));
    const legL = new THREE.Mesh(legGeo, darkMat);
    legL.position.set(-0.4, 0.3, 0);
    const legR = new THREE.Mesh(legGeo, darkMat);
    legR.position.set(0.4, 0.3, 0);
    group.add(legL, legR);
    leftLeg = legL;
    rightLeg = legR;

  } else {
    // Bolt: Skyblue navy robot yellow circular eyes segmented fists
    const skyMat = makeMat('#5aaae8', 0.6);
    const navyMat = makeMat('#1f3354', 0.5);
    const yellowMat = makeMat('#ffdd33', 0.4);
    const glowMat = makeMat('#ffffff', 0.2);

    const chassis = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(1.0, 0.9, 0.8, 3, 0.07)), skyMat);
    chassis.position.y = 1.1;
    const chestPlate = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.7, 0.6, 0.15, 3, 0.07)), navyMat);
    chestPlate.position.set(0, 1.1, 0.4);
    group.add(chassis, chestPlate);

    const head = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.7, 0.6, 0.6, 3, 0.07)), skyMat);
    head.position.set(0, 1.85, 0);
    const visor = new THREE.Mesh(makeGeo(new RoundedBoxGeometry(0.55, 0.25, 0.1, 3, 0.07)), navyMat);
    visor.position.set(0, 1.85, 0.3);
    const antenna = new THREE.Mesh(makeGeo(new THREE.CylinderGeometry(0.04, 0.04, 0.35, 6)), yellowMat);
    antenna.position.set(0, 2.3, 0);
    group.add(head, visor, antenna);

    const eyeGeo = makeGeo(new THREE.CylinderGeometry(0.08, 0.08, 0.06, 12));
    const eyeL = new THREE.Mesh(eyeGeo, yellowMat);
    eyeL.rotation.x = Math.PI / 2;
    eyeL.position.set(-0.16, 1.85, 0.35);
    const eyeR = new THREE.Mesh(eyeGeo, yellowMat);
    eyeR.rotation.x = Math.PI / 2;
    eyeR.position.set(0.16, 1.85, 0.35);
    group.add(eyeL, eyeR);

    const armGeo = makeGeo(new THREE.CylinderGeometry(0.12, 0.12, 0.5, 6));
    const fistGeo = makeGeo(new RoundedBoxGeometry(0.38, 0.38, 0.38, 3, 0.07));
    const armL = new THREE.Group();
    armL.position.set(-0.7, 1.3, 0);
    const amL = new THREE.Mesh(armGeo, navyMat);
    amL.position.y = -0.2;
    const fmL = new THREE.Mesh(fistGeo, glowMat);
    fmL.position.y = -0.55;
    armL.add(amL, fmL);

    const armR = new THREE.Group();
    armR.position.set(0.7, 1.3, 0);
    const amR = new THREE.Mesh(armGeo, navyMat);
    amR.position.y = -0.2;
    const fmR = new THREE.Mesh(fistGeo, glowMat);
    fmR.position.y = -0.55;
    armR.add(amR, fmR);
    group.add(armL, armR);
    leftArm = armL;
    rightArm = armR;

    const legGeo = makeGeo(new RoundedBoxGeometry(0.32, 0.55, 0.4, 3, 0.07));
    const legL = new THREE.Mesh(legGeo, navyMat);
    legL.position.set(-0.35, 0.3, 0);
    const legR = new THREE.Mesh(legGeo, navyMat);
    legR.position.set(0.35, 0.3, 0);
    group.add(legL, legR);
    leftLeg = legL;
    rightLeg = legR;
  }

  group.traverse((c) => {
    if (c instanceof THREE.Mesh) {
      c.castShadow = true;
      c.receiveShadow = true;
    }
  });

  return {
    group,
    animate: (dt: number, player: GameState['player'], moving: boolean) => {
      group.position.set(player.x, 0, player.z);
      group.rotation.y = player.angle;

      if (moving) {
        walkCycle += dt * 11;
        const swing = Math.sin(walkCycle) * 0.45;
        if (leftLeg) leftLeg.rotation.x = swing;
        if (rightLeg) rightLeg.rotation.x = -swing;
        if (leftArm) leftArm.rotation.x = -swing;
        if (rightArm) rightArm.rotation.x = swing;
        if (tail) tail.rotation.y = Math.sin(walkCycle * 0.7) * 0.35;
      } else {
        if (leftLeg) leftLeg.rotation.x *= 0.8;
        if (rightLeg) rightLeg.rotation.x *= 0.8;
        if (leftArm) leftArm.rotation.x *= 0.8;
        if (rightArm) rightArm.rotation.x *= 0.8;
        if (tail) tail.rotation.y *= 0.8;
      }
    },
    dispose: () => {
      cleanups.forEach(fn => fn());
    }
  };
}
