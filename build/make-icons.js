// Generate every icon file from the SVG masters in assets/brand/.
//
//     npm run build:icons
//
// The masters are the only hand-edited artwork; everything this writes is
// derived and committed, so a build never depends on running it. Run it again
// after changing a master.
//
// Two masters per product: the detailed mark (iris + signal trace) for 32 px
// and up, and a simplified one (ring + pupil) for 16-24 px, where the trace
// turns into noise. The hub's marks carry a node badge so the two programs are
// told apart in a taskbar and in Programs and Features.
//
// .ico layout: 32-bit BMP frames up to 64 px and PNG frames at 128 and 256 px.
// Every consumer here -- electron-builder, rcedit, PyInstaller, NSIS and
// Explorer -- reads that layout; PNG-only icons are not universally accepted
// at small sizes.

'use strict';

const fs = require('fs');
const path = require('path');
const { Resvg } = require('@resvg/resvg-js');

const ROOT = path.join(__dirname, '..');
const BRAND = path.join(ROOT, 'assets', 'brand');

const ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256];
const SMALL_MAX = 24; // at or below this, use the simplified master
const PNG_MIN = 128; // at or above this, store the frame as PNG

function master(name) {
  return fs.readFileSync(path.join(BRAND, `${name}.svg`), 'utf8');
}

function render(svg, size) {
  return new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render();
}

// resvg returns premultiplied RGBA; a BMP icon frame is straight-alpha BGRA,
// stored bottom-up, followed by a 1-bit AND mask (all zero: alpha decides).
function bmpFrame(image, size) {
  const px = image.pixels;
  const maskStride = Math.ceil(size / 32) * 4;
  const header = Buffer.alloc(40);
  header.writeUInt32LE(40, 0);
  header.writeInt32LE(size, 4);
  header.writeInt32LE(size * 2, 8); // XOR + AND masks
  header.writeUInt16LE(1, 12);
  header.writeUInt16LE(32, 14);
  header.writeUInt32LE(size * size * 4 + maskStride * size, 20);
  const body = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const src = (y * size + x) * 4;
      const dst = ((size - 1 - y) * size + x) * 4;
      const a = px[src + 3];
      const un = (c) => (a === 0 ? 0 : Math.min(255, Math.round((c * 255) / a)));
      body[dst] = un(px[src + 2]);
      body[dst + 1] = un(px[src + 1]);
      body[dst + 2] = un(px[src]);
      body[dst + 3] = a;
    }
  }
  return Buffer.concat([header, body, Buffer.alloc(maskStride * size)]);
}

function ico(fullName, smallName) {
  const full = master(fullName);
  const small = master(smallName);
  const frames = ICO_SIZES.map((size) => {
    const image = render(size <= SMALL_MAX ? small : full, size);
    return { size, data: size >= PNG_MIN ? image.asPng() : bmpFrame(image, size) };
  });
  const dir = Buffer.alloc(6 + 16 * frames.length);
  dir.writeUInt16LE(0, 0);
  dir.writeUInt16LE(1, 2);
  dir.writeUInt16LE(frames.length, 4);
  let offset = dir.length;
  frames.forEach((f, i) => {
    const e = 6 + 16 * i;
    dir.writeUInt8(f.size >= 256 ? 0 : f.size, e);
    dir.writeUInt8(f.size >= 256 ? 0 : f.size, e + 1);
    dir.writeUInt16LE(1, e + 4);
    dir.writeUInt16LE(32, e + 6);
    dir.writeUInt32LE(f.data.length, e + 8);
    dir.writeUInt32LE(offset, e + 12);
    offset += f.data.length;
  });
  return Buffer.concat([dir, ...frames.map((f) => f.data)]);
}

function write(relative, data) {
  const target = path.join(ROOT, relative);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, data);
  console.log(`  ${relative} (${data.length} bytes)`);
}

console.log('Icons from assets/brand/:');

// Desktop app. electron-builder picks build/icon.ico (Windows) and
// build/icon.png (Linux, 512 px) up without configuration.
write('build/icon.ico', ico('vrtelemetry-mark', 'vrtelemetry-mark-small'));
write('build/icon.png', render(master('vrtelemetry-mark'), 512).asPng());

// Hub: embedded in vrtelemetry-hub.exe by build/hub.spec and used by
// build/hub-installer.nsi.
write('build/hub-icon.ico', ico('vrtelemetry-hub-mark', 'vrtelemetry-hub-mark-small'));

// Browser tabs: an SVG favicon is drawn at 16 px, so it gets the simple mark.
write('src/frontend/VRTelemetry/public/favicon.svg', master('vrtelemetry-mark-small'));
write('src/central_server/admin_ui/favicon.svg', master('vrtelemetry-hub-mark-small'));
// The admin UI's login card and sidebar.
write('src/central_server/admin_ui/hub-mark.svg', master('vrtelemetry-hub-mark'));

// The desktop app's sidebar brand mark (34 px).
write('src/frontend/VRTelemetry/src/assets/vrtelemetry-mark.svg', master('vrtelemetry-mark'));
