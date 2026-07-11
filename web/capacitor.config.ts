import { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ai.raven.app",
  appName: "Raven AI",
  webDir: "dist",
  server: {
    androidScheme: "https",
    iosScheme: "https",
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      backgroundColor: "#0f1117",
      androidSplashResourceName: "splash",
      androidScaleType: "CENTER_CROP",
      showSpinner: false,
    },
    PushNotifications: {
      presentationOptions: ["badge", "sound", "alert"],
    },
    StatusBar: {
      style: "DARK",
      backgroundColor: "#0f1117",
    },
    Camera: {
      allowEditing: true,
      saveToGallery: false,
    },
    LocalNotifications: {
      smallIcon: "ic_stat_raven",
      iconColor: "#6366f1",
    },
    Network: {
      enabled: true,
    },
  },
};

export default config;
