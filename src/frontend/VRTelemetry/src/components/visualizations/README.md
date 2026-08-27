# Spatialviewer Doc

### Purpose
The `SpatialViewer` module is a 3D visualization component built with React Three Fiber that renders VR telemetry data in a spatial environment. It provides visual insights into user movement, eye-tracking vectors, volumetric gaze attention heatmaps, and oculomotor scanpaths.

### Key Components / Key Classes / Key Exports
- **`SpatialViewer`**: The primary exported component containing the main 3D canvas, lighting, camera controls, and overlay UI for toggling analytical visualization layers.
- **`VRRig`**: Renders the 3D representation of the HMD (head-mounted display), controllers, and eye tracking rays based on real-time telemetry frames.
- **`LivePoRCursor`**: Computes and displays the live point of regard (PoR) cursor dynamically via ray convergence calculations.
- **`AnalyticalLayers`**: Manages and renders instanced meshes for voxel-based attention heatmaps and oculomotor scanpath fixations/trajectories.

### Integration Points
This module integrates directly with `useTelemetryStore` to pull real-time or recorded frame data for positioning 3D objects, calculating gaze intersections, and analyzing historical session paths.

---

## Folder & File Structure

Here is the layout of files and subfolders contained within this path:

```text
visualizations/
├── README.md
└── SpatialViewer.tsx
```