const { app, BrowserWindow, dialog, net, protocol } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');
const { startBackend, stopBackend } = require('./backend-manager');

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
function registerAppProtocol() {
  const root = path.join(process.resourcesPath, 'frontend');

  protocol.handle(APP_SCHEME, (request) => {
    const { pathname } = new URL(request.url);
    const relative = decodeURIComponent(pathname).replace(/^\/+/, '') || 'index.html';
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
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  if (app.isPackaged) {
    await mainWindow.loadURL(`${APP_SCHEME}://./index.html`);
  } else {
    // Dev mode: point at the Vite dev server (npm run dev inside src/frontend/VRTelemetry)
    await mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  if (app.isPackaged) registerAppProtocol();

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