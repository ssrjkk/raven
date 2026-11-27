import { useEffect, useState } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export default function PWAInstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setShowPrompt(true);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  async function handleInstall() {
    if (!deferredPrompt) return;
    try {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === "accepted") {
        setShowPrompt(false);
      }
    } catch (e) {
      console.error("PWA install prompt failed:", e);
    }
    setDeferredPrompt(null);
  }

  if (!showPrompt) return null;

  return (
    <div
      className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 p-4 rounded-xl shadow-lg border text-sm max-w-sm w-full"
      style={{
        backgroundColor: "var(--dt-colors-bg-secondary)",
        borderColor: "var(--dt-colors-border-default)",
      }}
    >
      <div className="flex items-center gap-3 mb-3">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 17v3h14v-3" />
        </svg>
        <div>
          <div className="font-medium">Install Raven</div>
          <div className="text-tertiary">
            Add to home screen for the best experience
          </div>
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button
          onClick={() => setShowPrompt(false)}
          className="px-3 py-1.5 rounded-lg text-sm text-secondary"
        >
          Not now
        </button>
        <button
          onClick={handleInstall}
          className="px-3 py-1.5 rounded-lg text-sm font-medium bg-accent on-accent"
        >
          Install
        </button>
      </div>
    </div>
  );
}
