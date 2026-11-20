import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { wirePointerLight } from "./pointerLight";

/**
 * The storefront's pointer light, measured the way the console runs it: one listener over a tree that
 * remounts, coordinates written into the card being painted, and nothing left behind when the reader asks
 * for no motion.
 *
 * `site/landing.js` can afford a listener per card because its cards are in the first HTML and never leave.
 * The console mounts and unmounts its cards on every route change, so the same shape would add a listener
 * that outlives the node it points at -- a leak sized to how long someone works, invisible to a test that
 * mounts one card once. So the count itself is measured here, along with the three things a card can be
 * wrong about: coordinates that are the viewport's rather than the card's, a wash that stays where the
 * cursor was, and a frame scheduled per `pointermove` instead of per paint.
 */

type Frames = { scheduled: () => number[]; run: () => void };

let frames: Frames;
let reduceMotion = false;

function stubFrames(): Frames {
  const queue = new Map<number, FrameRequestCallback>();
  let handle = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    handle += 1;
    queue.set(handle, callback);
    return handle;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    queue.delete(id);
  });
  return {
    scheduled: () => [...queue.keys()],
    run: () => {
      const pending = [...queue.entries()];
      queue.clear();
      for (const [, callback] of pending) callback(performance.now());
    },
  };
}

function stubMatchMedia() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: /reduce/.test(query) && reduceMotion,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }));
}

/** A card the sheet washes, with the box the browser would report for it. */
function washed(className = "card", left = 100, top = 50): HTMLElement {
  const card = document.createElement("div");
  card.className = className;
  card.innerHTML = '<span class="inside">text</span>';
  document.body.append(card);
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({
    left,
    top,
    width: 300,
    height: 120,
    right: left + 300,
    bottom: top + 120,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect);
  return card;
}

function move(target: Element, clientX: number, clientY: number) {
  const event = new Event("pointermove", { bubbles: true });
  Object.assign(event, { clientX, clientY });
  target.dispatchEvent(event);
  return event;
}

function leave(target: Element, relatedTarget?: Element) {
  const event = new Event("pointerout", { bubbles: true });
  Object.assign(event, { clientX: 0, clientY: 0, relatedTarget });
  target.dispatchEvent(event);
  return event;
}

function wash(card: Element) {
  const style = (card as HTMLElement).style;
  return [style.getPropertyValue("--gx"), style.getPropertyValue("--gy")];
}

const teardowns: Array<() => void> = [];

function wire() {
  const off = wirePointerLight(document);
  teardowns.push(off);
  return off;
}

beforeEach(() => {
  reduceMotion = false;
  frames = stubFrames();
  stubMatchMedia();
});

afterEach(() => {
  while (teardowns.length) (teardowns.pop() as () => void)();
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the wash the console writes", () => {
  it("puts the cursor in the card's own coordinates, one frame late", () => {
    const card = washed();
    wire();
    const child = card.querySelector(".inside") as Element;

    move(child, 160, 90);
    expect(wash(card), "the frame has not run, so the card is still unwashed").toEqual(["", ""]);
    frames.run();
    expect(wash(card), "a cursor at 160,90 over a card whose box starts at 100,50").toEqual(["60px", "40px"]);
  });

  it("keeps the inline styles the card already carries", () => {
    // A wash written by building a `style` string replaces the attribute and takes the card's own
    // declarations with it; `setProperty` adds to them. The console hands maxHeight to a scroll card as an
    // inline style, so the second form is the only one that can share a card with the first.
    const card = washed("card");
    card.style.setProperty("max-height", "240px");
    wire();
    move(card, 130, 60);
    frames.run();
    expect(card.style.getPropertyValue("max-height")).toBe("240px");
    expect(wash(card)).toEqual(["30px", "10px"]);
  });

  it("schedules one frame per burst and answers the move that landed last", () => {
    const card = washed();
    wire();
    move(card, 120, 60);
    move(card, 180, 90);
    move(card, 200, 100);
    expect(frames.scheduled(), "every pointermove queued its own paint").toHaveLength(1);
    frames.run();
    expect(wash(card)).toEqual(["100px", "50px"]);

    move(card, 150, 70);
    expect(frames.scheduled(), "the flush forgot its handle and stopped scheduling").toHaveLength(1);
    frames.run();
    expect(wash(card)).toEqual(["50px", "20px"]);
  });

  it("washes the three selectors the sheet gives a wash, and nothing else", () => {
    wire();
    for (const className of ["card", "card-bordered", "stat-card"]) {
      const card = washed(className);
      move(card, 110, 55);
      frames.run();
      expect(wash(card), className).toEqual(["10px", "5px"]);
    }
    const plain = washed("panel");
    move(plain, 110, 55);
    expect(frames.scheduled(), "a card the sheet never washes still costs a frame").toEqual([]);
    expect(wash(plain)).toEqual(["", ""]);
  });
});

describe("what the light leaves behind", () => {
  it("centres the card the cursor moved off, and the one the reader left", () => {
    const first = washed("card", 0, 0);
    const second = washed("stat-card", 400, 0);
    wire();

    move(first, 10, 10);
    frames.run();
    move(second, 420, 20);
    expect(wash(first), "the card the cursor left is still half-lit").toEqual(["50%", "50%"]);
    frames.run();
    expect(wash(second)).toEqual(["20px", "20px"]);

    leave(second, document.body);
    expect(wash(second), "leaving the card left the wash at its last coordinates").toEqual(["50%", "50%"]);
  });

  it("does not reset a card the cursor is still inside", () => {
    // `pointerout` fires when the cursor crosses from a card to one of its own children, which is the same
    // card. Resetting there strobes the wash on every element boundary the card contains.
    const card = washed();
    wire();
    move(card, 160, 90);
    frames.run();
    leave(card, card.querySelector(".inside") as Element);
    expect(wash(card)).toEqual(["60px", "40px"]);
  });

  it("takes the wash away entirely under reduced motion, without a frame", () => {
    reduceMotion = true;
    const card = washed();
    wire();
    move(card, 160, 90);
    expect(frames.scheduled(), "reduced motion still queued a paint").toEqual([]);
    expect(wash(card), "a card can be left lit from before the preference was set").toEqual(["50%", "50%"]);
  });
});

describe("the listeners it costs", () => {
  it("adds one pair for the whole tree, not one per card", () => {
    // Spied on the prototype, because the shape being refused is a listener attached to the card: an
    // addEventListener counted on `document` alone would still read "one pair" while each card collected
    // its own, which is the leak `site/landing.js` has and this module exists to not repeat.
    const listen = vi.spyOn(EventTarget.prototype, "addEventListener");
    const unlisten = vi.spyOn(EventTarget.prototype, "removeEventListener");
    const pointerNames = (calls: Array<{ 0?: unknown }>) =>
      calls
        .map((call) => String(call[0]))
        .filter((type) => type.startsWith("pointer"))
        .sort();

    wire();
    const off = teardowns.pop() as () => void;
    expect(pointerNames(listen.mock.calls), "the wiring did not attach the pair it promises").toEqual([
      "pointermove",
      "pointerout",
    ]);

    // 200 cards mount, take the light and unmount behind that pair, which is the shape a long session
    // actually has: a listener per card is a leak sized to how long someone works, and nothing in a
    // single-mount test would ever see it.
    for (let i = 0; i < 200; i += 1) {
      listen.mockClear();
      const card = washed("card");
      move(card, 105, 55);
      frames.run();
      card.remove();
      expect(pointerNames(listen.mock.calls), `the ${i}th card added a listener of its own`).toEqual([]);
    }

    off();
    expect(pointerNames(unlisten.mock.calls), "teardown left one of the two attached").toEqual([
      "pointermove",
      "pointerout",
    ]);
    const late = washed();
    move(late, 105, 55);
    expect(frames.scheduled(), "a torn-down wiring still answers pointermove").toEqual([]);
    expect(wash(late)).toEqual(["", ""]);
  });
});
