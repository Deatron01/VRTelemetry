const { app, BrowserWindow, dialog } = require('electron');
const path = require('path');
const { startBackend, stopBackend } = require('./backend-manager');

let mainWindow = null;

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'VRTelemetry Research Studio',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  const frontendEntry = app.isPackaged
    ? path.join(process.resourcesPath, 'frontend', 'index.html')
    : null;

  if (app.isPackaged) {
    await mainWindow.loadFile(frontendEntry);
  } else {
    // Dev mode: point at the Vite dev server (npm run dev inside src/frontend/VRTelemetry)
    await mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  try {
    await startBackend();
  } catch (err) {
    dialog.showErrorBox(
      'Backend failed to start',
      `The telemetry engine could not be started:\n\n${err.message}`
    );
    app.quit();
    return;
  }
  await createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});