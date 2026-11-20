/** The storefront's pointer light, wired for a tree that mounts and unmounts.
 *
 * `site/landing.js` attaches a listener to each card, which is fine on a page whose cards are in the
 * first HTML and wrong here: the console remounts its cards on every route, and a listener per card is
 * a leak proportional to how long someone works. One delegated listener answers the whole tree, and the
 * coordinates are written through the CSSOM rather than a `style` attribute, so the card's own inline
 * styles and the CSP are both unaffected.
 *
 * A `requestAnimationFrame` sits in front of the writes because `pointermove` fires faster than a frame
 * on a 120 Hz mouse, and each write invalidates the paint of every card under the cursor.
 */

/** The cards the sheet gives a wash: `.card`, `.card-bordered` and `.stat-card` all read `--gx`/`--gy`. */
const WASHED = ".card, .card-bordered, .stat-card";

const CENTRE = "50%";

export function wirePointerLight(root: Document = document): () => void {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let target: HTMLElement | null = null;
  let event: PointerEvent | null = null;
  let frame = 0;

  const flush = () => {
    frame = 0;
    const card = target;
    const move = event;
    if (!card || !move) return;
    const box = card.getBoundingClientRect();
    card.style.setProperty("--gx", `${move.clientX - box.left}px`);
    card.style.setProperty("--gy", `${move.clientY - box.top}px`);
  };

  const centre = (card: HTMLElement) => {
    card.style.setProperty("--gx", CENTRE);
    card.style.setProperty("--gy", CENTRE);
  };

  const onMove = (move: PointerEvent) => {
    const card = move.target instanceof Element ? move.target.closest<HTMLElement>(WASHED) : null;
    if (!card) return;
    // Reduced motion takes the light away entirely: a wash that follows the cursor is the motion the
    // reader asked not to have, and a card left half-lit from the last move is worse than a plain one.
    if (reducedMotion.matches) {
      centre(card);
      return;
    }
    if (target && target !== card) centre(target);
    target = card;
    event = move;
    if (!frame) frame = requestAnimationFrame(flush);
  };

  const onLeave = (move: PointerEvent) => {
    const card = move.target instanceof Element ? move.target.closest<HTMLElement>(WASHED) : null;
    if (!card) return;
    const next = move.relatedTarget;
    if (next instanceof Node && card.contains(next)) return;
    centre(card);
    if (target === card) target = null;
  };

  root.addEventListener("pointermove", onMove);
  root.addEventListener("pointerout", onLeave);
  return () => {
    if (frame) cancelAnimationFrame(frame);
    root.removeEventListener("pointermove", onMove);
    root.removeEventListener("pointerout", onLeave);
  };
}
