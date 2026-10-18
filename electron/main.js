const { app, BrowserWindow, dialog, net, protocol } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');
const { startBackend, stopBackend } = require('./backend-manager');

// Packaged, the window and taskbar take the icon embedded in the executable
// (build/icon.ico, which electron-builder applies). In development the
// executable is Electron's own, so point the windows at the generated PNG.
const DEV_ICON = app.isPackaged ? {} : { icon: path.join(__dirname, '..', 'build', 'icon.png') };

let mainWindow = null;

// The packaged renderer is served from app:// rather than loaded with
// loadFile() (VRT-16).
//
// A file:// page has the opaque origin `null`, so every fetch() it makes to the
// backend on 127.0.0.1:8000 is a cross-origin request from an origin the API's
// CORS allow-list does not contain -- and must not contain, because `null` is
// also the origin of every sandboxed iframe on every website, and this API
// serves patient records and starts recordings. Verified: with `Origin: null`
// the API returns no Access-Control-Allow-Origin header at all, so the browser
// discards the response.
//
// The result was that the packaged app's UI could not talk to its own backend.
// Nobody hit it because the packaged app has never been buildable -- its
// PyInstaller spec did not exist until VRT-2, and before that it froze the CLI
// recorder, which never binds a port.
//
// `app://.` is the origin `src/config/settings.py` has listed all along; this
// is the half that was missing. Registered as standard and secure so it gets a
// real, unique origin, and so fetch() works from it at all.
const APP_SCHEME = 'app';

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true },
  },
]);

// Serve the packaged frontend out of resources/frontend, refusing anything that
// escapes it: the path comes from a URL, and `..` in a URL is a directory
// traversal against the user's disk.
//
// monitor.html is the one page that lives beside this file rather than in the
// frontend build. It fetches /api/monitor/metrics, so it needs the same app://
// origin as the main window -- which is also why the scheme is registered in
// development, where only the monitor window uses it.
function registerAppProtocol() {
  const root = path.join(process.resourcesPath, 'frontend');

  protocol.handle(APP_SCHEME, (request) => {
    const { pathname } = new URL(request.url);
    const relative = decodeURIComponent(pathname).replace(/^\/+/, '') || 'index.html';
    if (relative === 'monitor.html') {
      return net.fetch(pathToFileURL(path.join(__dirname, 'monitor.html')).toString());
    }
    const resolved = path.resolve(root, relative);

    if (resolved !== root && !resolved.startsWith(root + path.sep)) {
      return new Response('Not found', { status: 404 });
    }
    return net.fetch(pathToFileURL(resolved).toString());
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'VRTelemetry Research Studio',
    ...DEV_ICON,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  // Listen before loading. ready-to-show can fire before loadURL() resolves --
  // it does for the local app:// page -- and a listener added after the await
  // misses it, leaving the window loaded but never shown.
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });

  if (app.isPackaged) {
    await mainWindow.loadURL(`${APP_SCHEME}://./index.html`);
  } else {
    // Dev mode: point at the Vite dev server (npm run dev inside src/frontend/VRTelemetry)
    await mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

let monitorWindow = null;
function createMonitorWindow() {
  monitorWindow = new BrowserWindow({
    width: 300,
    height: 400,
    title: 'PC Monitor',
    ...DEV_ICON,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
    show: false,
    autoHideMenuBar: true,
    alwaysOnTop: true,
  });

  monitorWindow.once('ready-to-show', () => monitorWindow.show());
  monitorWindow.on('closed', () => { monitorWindow = null; });
  monitorWindow.loadURL(`${APP_SCHEME}://./monitor.html`);
}

// One instance. A second shell would start a second backend that cannot bind
// 127.0.0.1:8000, then talk to the first one's -- and quitting the first shell
// stops the backend under the second. A second launch brings the running
// window forward instead.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
}

app.whenReady().then(async () => {
  if (!app.hasSingleInstanceLock()) return;
  registerAppProtocol();

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
  createMonitorWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
      createMonitorWindow();
    }
  });
});

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  stopBackend();
});
