"use strict";

/* The storefront's pointer light for a document that loads no bundle.
 *
 * `web/src/design/pointerLight.ts` is the SPA's version; this is the same delegated listener in the page's
 * own JavaScript, because a listener per bubble would leak proportional to how long someone works and an
 * inline script is not allowed here at all (MV3 CSP). The coordinates go through the CSSOM, so the only thing
 * that ever reaches a bubble's style attribute is where the cursor is -- the sheet decides what the light is
 * painted with.
 */

const CENTRE = "50%";

export function wirePointerLight(washed, root = document) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let target = null;
  let move = null;
  let frame = 0;

  const centre = (card) => {
    card.style.setProperty("--gx", CENTRE);
    card.style.setProperty("--gy", CENTRE);
  };

  const flush = () => {
    frame = 0;
    if (!target || !move) return;
    const box = target.getBoundingClientRect();
    target.style.setProperty("--gx", `${move.clientX - box.left}px`);
    target.style.setProperty("--gy", `${move.clientY - box.top}px`);
  };

  const hit = (event) => (event.target instanceof Element ? event.target.closest(washed) : null);

  const onMove = (event) => {
    const card = hit(event);
    if (!card) return;
    // Reduced motion takes the light away rather than freezing it half-travelled.
    if (reducedMotion.matches) {
      centre(card);
      return;
    }
    if (target && target !== card) centre(target);
    target = card;
    move = event;
    if (!frame) frame = requestAnimationFrame(flush);
  };

  const onLeave = (event) => {
    const card = hit(event);
    if (!card) return;
    const next = event.relatedTarget;
    if (next instanceof Node && card.contains(next)) return;
    centre(card);
    if (target === card) target = null;
  };

  root.addEventListener("pointermove", onMove);
  root.addEventListener("pointerout", onLeave);
}
