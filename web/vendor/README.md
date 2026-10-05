# web/vendor — 함께 넣은 외부 라이브러리

인터넷 없이도 화면이 돌도록 빌드 파일만 넣었다. 원본 저장소는 넣지 않았다.

| 파일 | 라이브러리 | 라이선스 | 출처 |
|---|---|---|---|
| `gsap.min.js` | GSAP 3 | GreenSock Standard "No Charge" License (무료, 상업 사용 포함) | https://gsap.com/standard-license |
| `three.module.min.js`, `RoomEnvironment.js` | three.js 0.169.0 | MIT | https://github.com/mrdoob/three.js |
| `html2canvas.min.js` | html2canvas 1.4.1 | MIT | https://github.com/niklasvh/html2canvas |
| `liquid-glass/` (`container.js`, `button.js`, `glass.css`, `LICENSE`) | liquid-glass-js | MIT, Copyright (c) 2025 Armagan Amcalar | https://github.com/dashersw/liquid-glass-js |
| `thinking-orbs.js` | thinking-orbs 엔진 (`tools/orbs_entry.ts`를 esbuild로 묶음) | MIT, Copyright (c) 2026 Jakub Antalik | https://github.com/Jakubantalik/thinking-orbs |

글꼴(Pretendard, Space Grotesk, Noto Sans, JetBrains Mono, Material Symbols)과 Tailwind CSS는 CDN에서 받는다.
