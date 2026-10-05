// thinking-orbs(MIT, Jakub Antalik)의 캔버스 엔진만 묶어 React 없이 쓰는 진입점.
// 묶기: npx esbuild tools/orbs_entry.ts --bundle --minify --format=iife --outfile=web/vendor/thinking-orbs.js
// 사용: ThinkingOrbs.mount(canvas, { state: 'searching', size: 64, dark: true }) → 멈출 때 쓰는 함수를 돌려준다.
import { MODE_DRAWS } from '../thinking-orbs-main/src/engine/registry';
import { resolvePreset } from '../thinking-orbs-main/src/presets';

type Opts = { state?: string; size?: 20 | 64 | number; dark?: boolean; speed?: number };

function mount(canvas: HTMLCanvasElement, o: Opts = {}): () => void {
  const size = o.size ?? 64;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(size * dpr);
  canvas.height = Math.round(size * dpr);
  canvas.style.width = canvas.style.height = `${size}px`;
  const ctx = canvas.getContext('2d');
  if (!ctx) return () => {};
  // biome-ignore lint: 상태 이름은 라이브러리 목록 안에서 고른다
  const { mode, speed, opts } = resolvePreset((o.state ?? 'working') as any, size as any);
  const draw = MODE_DRAWS[mode];
  const eff = speed * (o.speed ?? 1);
  const frame = (t: number) => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    draw(ctx, size, t, !!o.dark, opts);
  };
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    frame(0.6);
    return () => {};
  }
  let raf = 0;
  let on = true;
  const loop = () => {
    frame((performance.now() / 1000) * eff);
    if (on) raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return () => {
    on = false;
    cancelAnimationFrame(raf);
  };
}

(window as unknown as { ThinkingOrbs: unknown }).ThinkingOrbs = { mount };
