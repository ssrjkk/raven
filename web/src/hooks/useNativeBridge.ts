import { useCallback, useEffect, useState } from "react";

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

  const isCapacitor = typeof (window as any).Capacitor !== "undefined"
    && (window as any).Capacitor.isNativePlatform();

  useEffect(() => {
    if (!isCapacitor) return;

    // Detect platform
    const cap = (window as any).Capacitor;
    const platform = cap.getPlatform();

    // Register push
    cap.Plugins.PushNotifications?.requestPermissions().then((perm: any) => {
      if (perm.receive === "granted") {
        cap.Plugins.PushNotifications.register();
        cap.Plugins.PushNotifications.addListener("registration", (r: any) => {
          setState((s) => ({ ...s, pushToken: r.token?.value || null }));
        });
      }
    });

    // Network listener
    cap.Plugins.Network?.addListener("networkStatusChange", (s: any) => {
      setState((st) => ({ ...st, isOnline: s.connected, connectionType: s.connectionType }));
    });

    // Hide splash
    cap.Plugins.SplashScreen?.hide();

    // Set status bar
    cap.Plugins.StatusBar?.setStyle({ style: "DARK" });

    setState((s) => ({ ...s, platform, isNative: true }));
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
      const cap = (window as any).Capacitor;
      const image = await cap.Plugins.Camera.getPhoto({
        resultType: "DataUrl",
        source: "Camera",
        quality: 90,
      });
      return image.dataUrl || null;
    } catch {
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
      const cap = (window as any).Capacitor;
      const image = await cap.Plugins.Camera.getPhoto({
        resultType: "DataUrl",
        source: "Photos",
        quality: 90,
      });
      return image.dataUrl || null;
    } catch {
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
      const cap = (window as any).Capacitor;
      const pos = await cap.Plugins.Geolocation.getCurrentPosition();
      return { lat: pos.coords.latitude, lng: pos.coords.longitude };
    } catch {
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
    const cap = (window as any).Capacitor;
    await cap.Plugins.LocalNotifications.schedule({
      notifications: [
        { title, body, id: Date.now(), schedule: delayMs ? { at: new Date(Date.now() + delayMs) } : undefined },
      ],
    });
  }, [isCapacitor]);

  const vibrate = useCallback(async (style: "light" | "medium" | "heavy" = "medium") => {
    if (!isCapacitor) {
      navigator.vibrate?.(style === "heavy" ? 50 : style === "medium" ? 25 : 10);
      return;
    }
    const cap = (window as any).Capacitor;
    const impactMap = { light: "Light", medium: "Medium", heavy: "Heavy" };
    await cap.Plugins.Haptics?.impact({ style: impactMap[style] });
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
