import { useRef, useEffect } from 'react';

interface RevealLayerProps {
  image: string;
  cursorX: number;
  cursorY: number;
}

const SPOTLIGHT_R = 260;

// P2 修复：用 CSS radial-gradient mask 替代 canvas.toDataURL()——后者每帧生成全屏 PNG
// 当 mask（几 MB），光标移动时明显卡顿。CSS mask 由浏览器原生合成，几乎零开销。
export default function RevealLayer({ image, cursorX, cursorY }: RevealLayerProps) {
  const revealRef = useRef<HTMLDivElement>(null);
  const cursorRef = useRef({ x: cursorX, y: cursorY });

  cursorRef.current = { x: cursorX, y: cursorY };

  const draw = () => {
    const revealDiv = revealRef.current;
    if (!revealDiv) return;

    const cx = cursorRef.current.x;
    const cy = cursorRef.current.y;

    if (cx < 0 && cy < 0) {
      // 光标未进入页面——整层隐藏（mask 全透明）
      revealDiv.style.maskImage = 'none';
      revealDiv.style.webkitMaskImage = 'none';
      return;
    }

    const mask = [
      `radial-gradient(circle at ${cx}px ${cy}px,`,
      'white 0%, white 40%,',
      'rgba(255,255,255,0.75) 60%,',
      'rgba(255,255,255,0.4) 75%,',
      'rgba(255,255,255,0.12) 88%,',
      'rgba(255,255,255,0) 100%)',
    ].join(' ');
    revealDiv.style.maskImage = mask;
    revealDiv.style.webkitMaskImage = mask;
    revealDiv.style.maskSize = '100% 100%';
    revealDiv.style.webkitMaskSize = '100% 100%';
  };

  useEffect(() => {
    draw();
  }, [cursorX, cursorY]);

  useEffect(() => {
    const handleResize = () => draw();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div
      ref={revealRef}
      className="absolute inset-0 bg-center bg-cover bg-no-repeat z-30 pointer-events-none"
      style={{ backgroundImage: `url(${image})` }}
    />
  );
}
