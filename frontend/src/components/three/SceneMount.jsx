import { Component, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';

// three.js lives in its own chunk, fetched only when a scene is about to show.
const PipelineScene = lazy(() => import('./PipelineScene'));

function webglAvailable() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
  } catch {
    return false;
  }
}

/** If WebGL fails for any reason the scene simply isn't there; the page is unaffected. */
class SceneBoundary extends Component {
  constructor(props) { super(props); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? null : this.props.children; }
}

/**
 * Decorative 3D scene. Loads only when near the viewport, pauses when it
 * scrolls away or the tab is hidden, and holds a still frame for visitors who
 * prefer reduced motion. Hidden from assistive tech and never takes clicks.
 */
export default function SceneMount({ className = '', lineColor, packets }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState !== 'hidden');
  const [supported] = useState(webglAvailable);

  useEffect(() => {
    const el = ref.current;
    if (!el || !supported) return undefined;
    const io = new IntersectionObserver(([entry]) => {
      setVisible(entry.isIntersecting);
      if (entry.isIntersecting) setMounted(true);
    }, { rootMargin: '200px 0px' });
    io.observe(el);
    const onVis = () => setPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', onVis);
    return () => { io.disconnect(); document.removeEventListener('visibilitychange', onVis); };
  }, [supported]);

  // Fewer packets on small screens keeps phones cool.
  const count = packets ?? (window.matchMedia('(max-width: 640px)').matches ? 16 : 30);

  return (
    <div ref={ref} aria-hidden="true" className={`scene ${mounted ? 'scene--in' : ''} ${className}`}>
      {mounted && supported && (
        <SceneBoundary>
          <Suspense fallback={null}>
            <PipelineScene animate={visible && pageVisible && !reduced} lineColor={lineColor} packets={count} />
          </Suspense>
        </SceneBoundary>
      )}
    </div>
  );
}
