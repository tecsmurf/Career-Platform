import FloatingBubbleField from './FloatingBubbleField';
import ParallaxScene from './ParallaxScene';

/**
 * Fixed, full-viewport decorative layer behind the page: soft out-of-focus
 * glass spheres (ambient) plus an optional field of company bubbles.
 * Never interactive, never in the accessibility tree.
 */
export default function BubbleBackground({ companies, density = 'dense', ambient = true, className = '' }) {
  return (
    <div className={`bubble-bg${className ? ` ${className}` : ''}`} aria-hidden="true">
      {ambient && (
        <>
          <span className="ambient ambient--a" />
          <span className="ambient ambient--b" />
          <span className="ambient ambient--c" />
        </>
      )}
      {companies?.length ? (
        <ParallaxScene className="bubble-bg__scene">
          <FloatingBubbleField companies={companies} density={density} />
        </ParallaxScene>
      ) : null}
    </div>
  );
}
