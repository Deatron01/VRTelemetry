const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const net = require('net');
const { app } = require('electron');

const BACKEND_PORT = 8000;
const BACKEND_HOST = '127.0.0.1';

let backendProcess = null;

function getBackendExecutablePath() {
  if (app.isPackaged) {
    // PyInstaller output, bundled as an extraResource — see package.json build config below
    const exeName = process.platform === 'win32' ? 'vrtelemetry-backend.exe' : 'vrtelemetry-backend';
    return path.join(process.resourcesPath, 'backend', exeName);
  }
  // Dev mode: run the Python source directly instead of the frozen exe
  return null;
}

// Where the packaged backend keeps sessions, patients.db, the licence cache and
// config.toml.
//
// Not the install directory. The backend's data root defaults to its working
// directory, and this used to be resources/backend -- so under Program Files
// recording could not write at all, and an upgrade or uninstall replaced
// resources/ and deleted every recording with it.
//
// %APPDATA%\VRTelemetry\data: per-user, because a folder one account creates
// under ProgramData is read-only to the next. The `data` subfolder keeps it
// apart from Chromium's own files in userData. VRT_PATHS__DATA_ROOT, if the lab
// set one, still wins.
//
// The backend is started *in* this directory as well as told about it:
// get_settings() reads config.toml from the working directory, and a relative
// central.ca_bundle resolves against it -- which is what lets the hub's
// workstation kit say `ca_bundle = "hub-ca.pem"`.
function getDataRoot() {
  const dataRoot = process.env.VRT_PATHS__DATA_ROOT || path.join(app.getPath('userData'), 'data');
  fs.mkdirSync(dataRoot, { recursive: true });
  return dataRoot;
}

function waitForPort(port, host, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tryConnect = () => {
      const socket = net.createConnection(port, host);
      socket.once('connect', () => {
        socket.end();
        resolve();
      });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Backend did not open port ${port} within ${timeoutMs}ms`));
        } else {
          setTimeout(tryConnect, 300);
        }
      });
    };
    tryConnect();
  });
}

async function startBackend() {
  if (app.isPackaged) {
    const exePath = getBackendExecutablePath();
    const dataRoot = getDataRoot();
    console.log(`Data root: ${dataRoot}`);
    backendProcess = spawn(exePath, [], {
      cwd: dataRoot,
      env: { ...process.env, VRT_PATHS__DATA_ROOT: dataRoot },
      stdio: 'pipe',
    });
  } else {
    // Dev mode: run the FastAPI app the same way your engineers already do,
    // via uvicorn against the existing src.main:app entrypoint.
    const projectRoot = path.join(__dirname, '..');
    backendProcess = spawn(
    process.platform === 'win32' ? 'python' : 'python3',
        ['-m', 'uvicorn', 'src.main:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)],
        { cwd: projectRoot, stdio: 'pipe' }
    );
  }

  backendProcess.stdout.on('data', (d) => console.log(`[backend] ${d}`.trim()));
  backendProcess.stderr.on('data', (d) => console.error(`[backend:err] ${d}`.trim()));
  backendProcess.on('exit', (code) => {
    console.log(`Backend process exited with code ${code}`);
    backendProcess = null;
  });

  await waitForPort(BACKEND_PORT, BACKEND_HOST);
  console.log('Backend is up and listening.');
}

function stopBackend() {
  if (backendProcess) {
    if (process.platform === 'win32') {
      // Ensures the whole process tree (uvicorn workers etc.) is killed on Windows
      spawn('taskkill', ['/pid', backendProcess.pid, '/f', '/t']);
    } else {
      backendProcess.kill('SIGTERM');
    }
    backendProcess = null;
  }
}

module.exports = { startBackend, stopBackend, BACKEND_PORT, BACKEND_HOST };
