import "@testing-library/jest-dom/vitest";

// Mock crypto.randomUUID for testing
if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis, "crypto", {
    value: {
      randomUUID: () => "00000000-0000-4000-8000-000000000000",
    },
    writable: true,
  });
}

// Mock localStorage
const store: Record<string, string> = {};
const localStorageMock: Storage = {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, value: string) => {
    store[key] = value;
  },
  removeItem: (key: string) => {
    delete store[key];
  },
  clear: () => {
    Object.keys(store).forEach((k) => delete store[k]);
  },
  get length() {
    return Object.keys(store).length;
  },
  key: (index: number) => Object.keys(store)[index] ?? null,
};
Object.defineProperty(globalThis, "localStorage", {
  value: localStorageMock,
  writable: true,
});
