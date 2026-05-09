import { app, BrowserWindow, Tray, Menu, nativeImage } from "electron";
import * as path from "path";

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;

const WEB_URL = process.env.RAVEN_URL || "http://localhost:18888";

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: "Raven AI",
    icon: path.join(__dirname, "../icon.png"),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(WEB_URL);

  mainWindow.on("close", (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function createTray() {
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip("Raven AI");

  const contextMenu = Menu.buildFromTemplate([
    { label: "Show", click: () => mainWindow?.show() },
    { label: "Hide", click: () => mainWindow?.hide() },
    { type: "separator" },
    { label: "Quit", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(contextMenu);

  tray.on("click", () => {
    mainWindow?.isVisible() ? mainWindow?.hide() : mainWindow?.show();
  });
}

app.on("ready", () => {
  createWindow();
  createTray();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
  else mainWindow.show();
});

declare module "electron" {
  interface App { isQuitting?: boolean; }
}
