// 시작 화면: 3D 비행기(three.js, 코드로 만든 모형) + 눈 로고 연출(GSAP) + 리퀴드 글래스 시작 버튼(liquid-glass-js).
// 비행기는 외부 3D 파일 없이 기본 도형으로 만든다. 움직임을 줄이는 설정이면 연출 없이 바로 보여 준다.
import * as THREE from 'three';
import { RoomEnvironment } from './vendor/RoomEnvironment.js';

const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const gsap = window.gsap;
const canvas = document.getElementById('sky');

// ------------------------------------------------------------------ 3D 장면
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch (e) {
  renderer = null;
}
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 200);
camera.position.set(0, 8.5, 25);
camera.lookAt(0, 1.4, 0);
const plane = new THREE.Group();
const rig = new THREE.Group();  // 마우스에 따라 살짝 기울어지는 바깥 틀
rig.add(plane);
scene.add(rig);

function buildPlane() {
  const skin = new THREE.MeshPhysicalMaterial({ color: 0xf5f7fb, metalness: 0.18, roughness: 0.3, clearcoat: 0.7, clearcoatRoughness: 0.25 });
  const trim = new THREE.MeshPhysicalMaterial({ color: 0xdfe6f0, metalness: 0.35, roughness: 0.35, clearcoat: 0.4 });
  const glass = new THREE.MeshPhysicalMaterial({ color: 0x1b2a44, metalness: 0.2, roughness: 0.15, clearcoat: 1 });
  const accent = new THREE.MeshStandardMaterial({ color: 0x2c7be5, metalness: 0.2, roughness: 0.4 });

  // 동체: 회전체(꼬리 → 기수), 길이 방향을 X축으로 눕힌다
  const prof = [[0.0, -5.2], [0.18, -5.0], [0.42, -4.3], [0.58, -3.3], [0.64, -2.0], [0.64, 3.0], [0.6, 3.7], [0.5, 4.3], [0.32, 4.8], [0.0, 5.15]]
    .map(([r, y]) => new THREE.Vector2(r, y));
  const body = new THREE.Mesh(new THREE.LatheGeometry(prof, 64), skin);
  body.rotation.z = -Math.PI / 2;
  plane.add(body);
  // 창문 띠와 조종석 창
  const band = new THREE.Mesh(new THREE.CylinderGeometry(0.645, 0.645, 6.2, 64, 1, true, Math.PI * 0.18, Math.PI * 0.08), accent);
  band.rotation.z = -Math.PI / 2;
  band.position.x = 0.3;
  plane.add(band);
  const cockpit = new THREE.Mesh(new THREE.SphereGeometry(0.62, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.22), glass);
  cockpit.rotation.z = -Math.PI / 2 - 0.55;
  cockpit.position.set(4.05, 0.12, 0);
  plane.add(cockpit);

  const extrude = (pts, depth) => {
    const s = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, z)));
    const g = new THREE.ExtrudeGeometry(s, { depth, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.03, bevelSegments: 3 });
    g.translate(0, 0, -depth / 2);
    return g;
  };
  // 주날개(뒤로 젖힌 형태), 양쪽에 대칭으로 붙이고 위로 약간 꺾는다
  const wingG = extrude([[1.5, 0], [-0.7, 5.6], [-1.45, 5.6], [-1.05, 0]], 0.1);
  for (const side of [1, -1]) {
    const w = new THREE.Mesh(wingG, skin);
    w.rotation.x = Math.PI / 2;
    w.scale.y = side;
    w.rotation.z = 0;
    w.position.set(0.2, -0.25, 0);
    w.rotation.order = 'XYZ';
    const holder = new THREE.Group();
    holder.add(w);
    holder.rotation.x = side * -0.08;
    plane.add(holder);
    // 엔진
    const eng = new THREE.Group();
    const nac = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.3, 1.5, 40), trim);
    nac.rotation.z = Math.PI / 2;
    const lip = new THREE.Mesh(new THREE.TorusGeometry(0.33, 0.05, 12, 40), skin);
    lip.rotation.y = Math.PI / 2;
    lip.position.x = 0.76;
    const fan = new THREE.Mesh(new THREE.CircleGeometry(0.3, 32), glass);
    fan.rotation.y = Math.PI / 2;
    fan.position.x = 0.74;
    eng.add(nac, lip, fan);
    eng.position.set(0.85, -0.72, side * 2.1);
    plane.add(eng);
    // 수평 꼬리날개
    const st = new THREE.Mesh(extrude([[-3.75, 0], [-4.75, 2.0], [-5.15, 2.0], [-4.75, 0]], 0.07), skin);
    st.rotation.x = Math.PI / 2;
    st.scale.y = side;
    st.position.y = 0.05;
    plane.add(st);
  }
  // 수직 꼬리날개
  const fin = new THREE.Mesh(extrude([[-3.4, 0.4], [-4.65, 2.55], [-5.15, 2.55], [-4.85, 0.4]], 0.08), skin);
  plane.add(fin);
  const finTip = new THREE.Mesh(extrude([[-4.55, 2.2], [-4.65, 2.55], [-5.15, 2.55], [-5.07, 2.2]], 0.085), accent);
  plane.add(finTip);
}

if (renderer) {
  buildPlane();
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc9d4e4, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 2.1);
  sun.position.set(6, 10, 8);
  scene.add(sun);
  plane.rotation.set(0.06, -0.62, 0.05);
  plane.position.set(0, 2.2, 0);
}

function resize() {
  if (!renderer) return;
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  // 좁은 화면에서는 비행기가 잘리지 않게 뒤로 물린다
  const a = w / h;
  camera.position.z = a < 1 ? 25 / a * 0.62 : 25;
  camera.position.y = a < 1 ? 8.5 / a * 0.62 : 8.5;
  camera.lookAt(0, 1.4, 0);
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

const pointer = { x: 0, y: 0 };
window.addEventListener('pointermove', (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
});

const clock = new THREE.Clock();
const shadowEl = document.getElementById('shadow');
const drift = { on: true, speed: 1 };
function tick() {
  const t = clock.getElapsedTime();
  if (drift.on && !reduce) {
    // 떠 있는 듯한 느린 흔들림과 마우스 쪽으로 살짝 기울기 (부드럽게 따라감)
    plane.position.y = 2.2 + Math.sin(t * 0.8) * 0.18;
    shadowEl.style.transform = 'translateX(-50%) scale(' + (1 - Math.sin(t * 0.8) * 0.05).toFixed(3) + ')';
    plane.rotation.z = 0.05 + Math.sin(t * 0.6) * 0.035;
    rig.rotation.y += ((pointer.x * 0.18) - rig.rotation.y) * 0.04;
    rig.rotation.x += ((pointer.y * 0.08) - rig.rotation.x) * 0.04;
  }
  if (renderer) renderer.render(scene, camera);
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// ------------------------------------------------------------------ 로고 연출
const $ = (s) => document.querySelector(s);
function splitChars(el) {
  el.innerHTML = [...el.textContent].map((c) => `<span class="ch">${c}</span>`).join('');
  return el.querySelectorAll('.ch');
}
const koChars = splitChars($('#ko'));
const enChars = splitChars($('#en'));

function intro() {
  if (!gsap || reduce) { mountGlass(); return; }
  const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });
  gsap.set('.lid', { strokeDasharray: 100, strokeDashoffset: 100 });
  gsap.set(['.iris', '.pupil', '.glint'], { opacity: 0, svgOrigin: '24 24' });
  gsap.set([koChars, enChars], { yPercent: 60, opacity: 0 });
  gsap.set(['#tagline', '#btn-wrap', '#foot'], { opacity: 0, y: 14 });
  if (renderer) {
    gsap.set(plane.position, { x: -22, y: 0.4, z: -6 });
    gsap.set(plane.rotation, { y: -0.95, z: 0.32 });
    tl.to(plane.position, { x: 0, y: 2.2, z: 0, duration: 2.6, ease: 'expo.out' }, 0)
      .to(plane.rotation, { y: -0.62, z: 0.05, duration: 2.8, ease: 'power3.out' }, 0)
      .fromTo('#shadow', { opacity: 0, scaleX: 0.4 }, { opacity: 1, scaleX: 1, duration: 2.4, ease: 'power3.out' }, 0.3);
  }
  tl.to('.lid', { strokeDashoffset: 0, duration: 1.1, ease: 'power2.inOut' }, 0.35)
    .fromTo('.iris', { opacity: 0, scale: 0.4, rotation: -200, svgOrigin: '24 24' }, { opacity: 1, scale: 1, rotation: -60, svgOrigin: '24 24', duration: 0.9, ease: 'expo.out' }, 1.0)
    .fromTo('.pupil', { opacity: 0, scale: 0, svgOrigin: '24 24' }, { opacity: 1, scale: 1, svgOrigin: '24 24', duration: 0.45, ease: 'back.out(2)' }, 1.25)
    .to('.glint', { opacity: 1, duration: 0.3 }, 1.5)
    .to('.logo-eye', { scaleY: 0.1, transformOrigin: '50% 50%', duration: 0.11, ease: 'power2.in', yoyo: true, repeat: 1 }, 1.75)
    .fromTo('.scan', { opacity: 0, attr: { x1: 6, x2: 6 } }, { opacity: 0.95, attr: { x1: 42, x2: 42 }, duration: 0.75, ease: 'power2.inOut' }, 2.05)
    .to('.scan', { opacity: 0, duration: 0.25 }, 2.7)
    .to(koChars, { yPercent: 0, opacity: 1, duration: 0.7, stagger: 0.06 }, 1.1)
    .to(enChars, { yPercent: 0, opacity: 1, duration: 0.5, stagger: 0.025 }, 1.35)
    .to('#tagline', { opacity: 1, y: 0, duration: 0.7 }, 1.8)
    .to('#btn-wrap', { opacity: 1, y: 0, duration: 0.7 }, 2.05)
    .to('#foot', { opacity: 1, y: 0, duration: 0.6 }, 2.3)
    .add(mountGlass, 2.9);
}

// ------------------------------------------------------------------ 시작 버튼
let leaving = false;
function go(e) {
  if (e) e.preventDefault();
  if (leaving) return;
  leaving = true;
  if (!gsap || reduce) { location.href = 'index.html'; return; }
  drift.on = false;
  const tl = gsap.timeline({ onComplete: () => { location.href = 'index.html'; } });
  tl.to('#shadow', { opacity: 0, duration: 0.6 }, 0);
  tl.to('#stage, #foot', { opacity: 0, y: -12, filter: 'blur(6px)', duration: 0.5, ease: 'power2.in' }, 0);
  if (renderer) {
    tl.to(plane.position, { x: 30, y: 4.5, z: 6, duration: 1.1, ease: 'power3.in' }, 0)
      .to(plane.rotation, { y: -0.2, z: -0.18, duration: 1.1, ease: 'power2.in' }, 0);
  }
  tl.to('body', { backgroundColor: '#F4F6FA', duration: 0.4 }, 0.7);
}
$('#start-fallback').addEventListener('click', go);

// liquid-glass-js 버튼: 페이지를 한 번 찍은 사진으로 굴절을 그리므로 연출이 끝난 뒤 만든다.
// 안 되면(WebGL 없음 등) 같은 자리의 CSS 유리 버튼을 그대로 쓴다.
function mountGlass() {
  try {
    // container.js/button.js는 일반 스크립트의 class 선언이라 window에 붙지 않는다. 전역 이름으로 찾는다.
    const GlassButton = typeof Button !== 'undefined' ? Button : null;  // eslint-disable-line no-undef
    if (!GlassButton || !window.html2canvas || !document.createElement('canvas').getContext('webgl')) return;
    const b = new GlassButton({ text: '시작하기', size: 22, type: 'pill', tintOpacity: 0.12, onClick: () => go() });
    const el = b.element;
    el.setAttribute('role', 'button');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-label', '시작하기');
    el.id = 'start-glass';
    el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') go(ev); });
    const wrap = $('#btn-wrap');
    const fb = $('#start-fallback');
    wrap.appendChild(el);
    fb.style.display = 'none';
    if (gsap && !reduce) gsap.from(el, { scale: 0.96, opacity: 0, duration: 0.5, ease: 'power3.out' });
  } catch (err) {
    console.warn('liquid glass unavailable', err);
  }
}

intro();
