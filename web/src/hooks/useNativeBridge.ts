import { useCallback, useEffect, useRef, useState } from "react";

interface CapacitorPlugin {
  PushNotifications?: {
    requestPermissions: () => Promise<{ receive: string }>;
    register: () => void;
    addListener: (event: "registration", cb: (data: { token?: { value?: string } }) => void) => { remove: () => void };
  };
  Network?: {
    addListener: (event: "networkStatusChange", cb: (data: { connected: boolean; connectionType: string }) => void) => { remove: () => void };
  };
  SplashScreen?: { hide: () => void };
  StatusBar?: { setStyle: (style: { style: string }) => void };
  LocalNotifications?: { schedule: (opts: { notifications: { title: string; body: string; id: number; schedule?: { at: Date } }[] }) => Promise<void> };
  Haptics?: { impact: (opts: { style: string }) => Promise<void> };
  Camera?: { getPhoto: (opts: { resultType: string; source: string; quality: number }) => Promise<{ dataUrl?: string }> };
  Geolocation?: { getCurrentPosition: () => Promise<{ coords: { latitude: number; longitude: number } }> };
}
interface CapacitorGlobal { Capacitor?: { isNativePlatform: () => boolean; Plugins: CapacitorPlugin; getPlatform: () => string } }
declare global { interface Window { Capacitor?: CapacitorGlobal['Capacitor'] } }

export interface NativeBridgeState {
  platform: "ios" | "android" | "web";
  isNative: boolean;
  pushToken: string | null;
  isOnline: boolean;
  connectionType: string;
}

/**
 * Hook that provides access to native mobile device features.
 * Returns a web fallback when not running in Capacitor.
 */
export function useNativeBridge() {
  const [state, setState] = useState<NativeBridgeState>({
    platform: "web",
    isNative: false,
    pushToken: null,
    isOnline: navigator.onLine,
    connectionType: navigator.onLine ? "wifi" : "none",
  });

  const isCapacitor = typeof window.Capacitor !== "undefined"
    && window.Capacitor!.isNativePlatform();

  const capListeners = useRef<Array<{ remove: () => void }>>([]);

  useEffect(() => {
    if (!isCapacitor) return;

    const cap = window.Capacitor!;
    const platform = cap.getPlatform();

    cap.Plugins.PushNotifications?.requestPermissions()
      .then((perm) => {
        if (perm.receive === "granted") {
          cap.Plugins.PushNotifications?.register();
          const pushListener = cap.Plugins.PushNotifications?.addListener("registration", (r) => {
            setState((s) => ({ ...s, pushToken: r.token?.value || null }));
          });
          if (pushListener) capListeners.current.push(pushListener);
        }
      })
      .catch((e) => console.error("push permissions:", e));

    const netListener = cap.Plugins.Network?.addListener("networkStatusChange", (s) => {
      setState((st) => ({ ...st, isOnline: s.connected, connectionType: s.connectionType }));
    });
    if (netListener) capListeners.current.push(netListener);

    cap.Plugins.SplashScreen?.hide();
    cap.Plugins.StatusBar?.setStyle({ style: "DARK" });

    setState((s) => ({ ...s, platform: platform as "ios" | "android" | "web", isNative: true }));

    return () => {
      for (const l of capListeners.current) l.remove();
      capListeners.current = [];
    };
  }, [isCapacitor]);

  const takePhoto = useCallback(async (): Promise<string | null> => {
    if (!isCapacitor) {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      input.capture = "environment";
      return new Promise((resolve) => {
        input.onchange = () => {
          const file = input.files?.[0];
          if (file) {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as string);
            reader.readAsDataURL(file);
          } else resolve(null);
        };
        input.click();
      });
    }
    try {
      const cap = window.Capacitor!;
      const image = await cap.Plugins.Camera?.getPhoto({
        resultType: "DataUrl",
        source: "Camera",
        quality: 90,
      });
      return image?.dataUrl || null;
    } catch (e) { console.error("useNativeBridge:", e);
      return null;
    }
  }, [isCapacitor]);

  const pickFromGallery = useCallback(async (): Promise<string | null> => {
    if (!isCapacitor) {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = "image/*";
      return new Promise((resolve) => {
        input.onchange = () => {
          const file = input.files?.[0];
          if (file) {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as string);
            reader.readAsDataURL(file);
          } else resolve(null);
        };
        input.click();
      });
    }
    try {
      const cap = window.Capacitor!;
      const image = await cap.Plugins.Camera?.getPhoto({
        resultType: "DataUrl",
        source: "Photos",
        quality: 90,
      });
      return image?.dataUrl || null;
    } catch (e) { console.error("useNativeBridge:", e);
      return null;
    }
  }, [isCapacitor]);

  const getLocation = useCallback(async (): Promise<{ lat: number; lng: number } | null> => {
    if (!isCapacitor) {
      if (!navigator.geolocation) return null;
      return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
          (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
          () => resolve(null),
        );
      });
    }
    try {
      const cap = window.Capacitor!;
      const pos = await cap.Plugins.Geolocation?.getCurrentPosition();
      return pos ? { lat: pos.coords.latitude, lng: pos.coords.longitude } : null;
    } catch (e) { console.error("useNativeBridge:", e);
      return null;
    }
  }, [isCapacitor]);

  const scheduleNotification = useCallback(async (title: string, body: string, delayMs?: number) => {
    if (!isCapacitor) {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
      }
      return;
    }
    const cap = window.Capacitor!;
    try {
      await cap.Plugins.LocalNotifications?.schedule({
        notifications: [
          { title, body, id: Date.now(), schedule: delayMs ? { at: new Date(Date.now() + delayMs) } : undefined },
        ],
      });
    } catch (e) { console.error("scheduleNotification:", e); }
  }, [isCapacitor]);

  const vibrate = useCallback(async (style: "light" | "medium" | "heavy" = "medium") => {
    if (!isCapacitor) {
      navigator.vibrate?.(style === "heavy" ? 50 : style === "medium" ? 25 : 10);
      return;
    }
    const cap = window.Capacitor!;
    const impactMap = { light: "Light", medium: "Medium", heavy: "Heavy" };
    try {
      await cap.Plugins.Haptics?.impact({ style: impactMap[style] });
    } catch (e) { console.error("vibrate:", e); }
  }, [isCapacitor]);

  return {
    ...state,
    takePhoto,
    pickFromGallery,
    getLocation,
    scheduleNotification,
    vibrate,
  };
}
