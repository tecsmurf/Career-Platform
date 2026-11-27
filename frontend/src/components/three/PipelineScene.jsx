import { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

// Same knot as the geometry below (TorusKnotGeometry, p = 2, q = 3), so the
// packets ride exactly on the wireframe.
const R = 1.5;
const P = 2;
const Q = 3;
function knotPoint(u, out) {
  const quOverP = (Q / P) * u;
  const cs = Math.cos(quOverP);
  return out.set(R * (2 + cs) * 0.5 * Math.cos(u), R * (2 + cs) * 0.5 * Math.sin(u), R * Math.sin(quOverP) * 0.5);
}

const scratch = new THREE.Vector3();
/** Move every packet along the knot by dt seconds. */
function advance(s, dt, count) {
  const pos = s.geo.attributes.position;
  for (let i = 0; i < count; i += 1) {
    s.phase[i] += dt * s.speed[i];
    knotPoint(s.phase[i], scratch);
    pos.setXYZ(i, scratch.x, scratch.y, scratch.z);
  }
  pos.needsUpdate = true;
}

// Status colours of the app: saved → applied → interview → offer.
const PACKET_COLORS = ['#9aa6bb', '#6d9bff', '#ffb21e', '#3ddc84'];

/** Soft round sprite so packets glow instead of rendering as squares. */
function useGlowTexture() {
  return useMemo(() => {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, 'rgba(255,255,255,1)');
    grad.addColorStop(0.25, 'rgba(255,255,255,0.85)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }, []);
}

/**
 * A wireframe knot (the pipeline) with glowing packets (applications) flowing
 * along it. Turns slowly, leans toward the pointer and winds as the page scrolls.
 */
function Pipeline({ animate, lineColor, packets }) {
  const group = useRef(null);
  const points = useRef(null);
  const texture = useGlowTexture();

  const knot = useMemo(
    () => new THREE.WireframeGeometry(new THREE.TorusKnotGeometry(R, 0.46, 110, 10, P, Q)),
    [],
  );

  // Each packet: a phase along the knot, its own speed and a status colour.
  const state = useMemo(() => {
    const phase = new Float32Array(packets);
    const speed = new Float32Array(packets);
    const positions = new Float32Array(packets * 3);
    const colors = new Float32Array(packets * 3);
    const c = new THREE.Color();
    for (let i = 0; i < packets; i += 1) {
      phase[i] = (i / packets) * Math.PI * 2 * P;
      speed[i] = 0.16 + ((i * 37) % 11) / 60;
      c.set(PACKET_COLORS[i % PACKET_COLORS.length]);
      colors.set([c.r, c.g, c.b], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const s = { phase, speed, geo };
    advance(s, 0, packets); // place once so a still (reduced-motion) frame shows the packets
    return s;
  }, [packets]);

  useFrame((s, delta) => {
    if (!animate || !group.current) return;
    const dt = Math.min(delta, 0.05);
    advance(state, dt, packets);
    group.current.rotation.y += dt * 0.12;
    const target = window.scrollY * 0.0012;
    group.current.rotation.x = THREE.MathUtils.lerp(group.current.rotation.x, 0.5 + target + s.pointer.y * 0.2, 0.06);
    group.current.rotation.z = THREE.MathUtils.lerp(group.current.rotation.z, s.pointer.x * 0.25, 0.06);
  });

  return (
    <group ref={group} rotation={[0.5, 0.3, 0]}>
      <lineSegments geometry={knot}>
        <lineBasicMaterial color={lineColor} transparent opacity={0.26} />
      </lineSegments>
      <points ref={points} geometry={state.geo}>
        <pointsMaterial size={0.34} map={texture} vertexColors transparent depthWrite={false}
          blending={THREE.AdditiveBlending} sizeAttenuation />
      </points>
    </group>
  );
}

export default function PipelineScene({ animate, lineColor = '#9dbbff', packets = 28 }) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 7.6], fov: 40 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      frameloop={animate ? 'always' : 'demand'}
      eventSource={document.body}
      eventPrefix="client"
      style={{ pointerEvents: 'none' }}
    >
      <Pipeline animate={animate} lineColor={lineColor} packets={packets} />
    </Canvas>
  );
}
