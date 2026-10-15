import { useRef, useMemo, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Grid, Line } from '@react-three/drei';
import * as THREE from 'three';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { Layers, Eye, Crosshair, Activity, Video } from 'lucide-react';
import { InfoTooltip } from '../InfoTooltip';
import { useSyncedVideo } from '../../hooks/useSyncedVideo';

const VRRig = () => {
  const hmdRef = useRef<THREE.Group>(null);
  const leftEyeRef = useRef<THREE.Group>(null);
  const rightEyeRef = useRef<THREE.Group>(null);
  const leftCtrlRef = useRef<THREE.Mesh>(null);
  const rightCtrlRef = useRef<THREE.Mesh>(null);

  useFrame(() => {
    const { frames, currentFrameIdx } = useTelemetryStore.getState();
    const frame = frames[currentFrameIdx];
    if (!frame || !hmdRef.current || !leftEyeRef.current || !rightEyeRef.current || !leftCtrlRef.current || !rightCtrlRef.current) return;

    if (frame.hmd_tracking_valid > 0) {
      hmdRef.current.position.set(frame.hmd_pos_x, frame.hmd_pos_y, frame.hmd_pos_z);
      hmdRef.current.quaternion.set(frame.hmd_rot_x, frame.hmd_rot_y, frame.hmd_rot_z, frame.hmd_rot_w);
      hmdRef.current.visible = true;
    } else {
      hmdRef.current.visible = false;
    }

    if (frame.left_pos_x !== undefined) {
      leftCtrlRef.current.position.set(frame.left_pos_x, frame.left_pos_y || 0, frame.left_pos_z || 0);
      leftCtrlRef.current.quaternion.set(frame.left_rot_x || 0, frame.left_rot_y || 0, frame.left_rot_z || 0, frame.left_rot_w || 1);
      leftCtrlRef.current.visible = true;
    } else {
      leftCtrlRef.current.visible = false;
    }

    if (frame.right_pos_x !== undefined) {
      rightCtrlRef.current.position.set(frame.right_pos_x, frame.right_pos_y || 0, frame.right_pos_z || 0);
      rightCtrlRef.current.quaternion.set(frame.right_rot_x || 0, frame.right_rot_y || 0, frame.right_rot_z || 0, frame.right_rot_w || 1);
      rightCtrlRef.current.visible = true;
    } else {
      rightCtrlRef.current.visible = false;
    }

    if (frame.eye_tracking_valid > 0) {
      leftEyeRef.current.position.set(-0.032, 0, -0.075);
      leftEyeRef.current.quaternion.set(frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w);
      leftEyeRef.current.visible = true;

      rightEyeRef.current.position.set(0.032, 0, -0.075);
      rightEyeRef.current.quaternion.set(frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w);
      rightEyeRef.current.visible = true;
    } else {
      leftEyeRef.current.visible = false;
      rightEyeRef.current.visible = false;
    }
  });

  return (
    <>
      <group ref={hmdRef}>
        <mesh>
          <boxGeometry args={[0.2, 0.12, 0.15]} />
          <meshStandardMaterial color="#3b82f6" transparent opacity={0.8} />
        </mesh>

        <group ref={leftEyeRef}>
          <mesh>
            <sphereGeometry args={[0.015, 16, 16]} />
            <meshBasicMaterial color="#ef4444" />
          </mesh>
          <Line points={[[0, 0, 0], [0, 0, -5]]} color="#a855f7" lineWidth={2} />
        </group>

        <group ref={rightEyeRef}>
          <mesh>
            <sphereGeometry args={[0.015, 16, 16]} />
            <meshBasicMaterial color="#ef4444" />
          </mesh>
          <Line points={[[0, 0, 0], [0, 0, -5]]} color="#a855f7" lineWidth={2} />
        </group>
      </group>

      <mesh ref={leftCtrlRef}>
        <sphereGeometry args={[0.04, 16, 16]} />
        <meshStandardMaterial color="#10b981" />
      </mesh>
      <mesh ref={rightCtrlRef}>
        <sphereGeometry args={[0.04, 16, 16]} />
        <meshStandardMaterial color="#ef4444" />
      </mesh>
    </>
  );
};

const LivePoRCursor = ({ visible }: { visible: boolean }) => {
  const cursorRef = useRef<THREE.Mesh>(null);

  useFrame(() => {
    if (!visible || !cursorRef.current) return;
    const { frames, currentFrameIdx } = useTelemetryStore.getState();
    const f = frames[currentFrameIdx];

    if (!f || f.eye_tracking_valid === 0 || f.hmd_tracking_valid === 0) {
      cursorRef.current.visible = false;
      return;
    }

    const hmdPos = new THREE.Vector3(f.hmd_pos_x, f.hmd_pos_y, f.hmd_pos_z);
    const hmdQuat = new THREE.Quaternion(f.hmd_rot_x || 0, f.hmd_rot_y || 0, f.hmd_rot_z || 0, f.hmd_rot_w ?? 1);

    const leftWorldPos = new THREE.Vector3(-0.032, 0, -0.075).applyQuaternion(hmdQuat).add(hmdPos);
    const rightWorldPos = new THREE.Vector3(0.032, 0, -0.075).applyQuaternion(hmdQuat).add(hmdPos);

    const leftWorldRot = hmdQuat.clone().multiply(new THREE.Quaternion(f.left_eye_rot_x || 0, f.left_eye_rot_y || 0, f.left_eye_rot_z || 0, f.left_eye_rot_w ?? 1));
    const rightWorldRot = hmdQuat.clone().multiply(new THREE.Quaternion(f.right_eye_rot_x || 0, f.right_eye_rot_y || 0, f.right_eye_rot_z || 0, f.right_eye_rot_w ?? 1));

    const d1 = new THREE.Vector3(0, 0, -1).applyQuaternion(leftWorldRot);
    const d2 = new THREE.Vector3(0, 0, -1).applyQuaternion(rightWorldRot);
    const p12 = new THREE.Vector3().subVectors(leftWorldPos, rightWorldPos);

    const d1d1 = d1.dot(d1); const d1d2 = d1.dot(d2); const d2d2 = d2.dot(d2);
    const d1p12 = d1.dot(p12); const d2p12 = d2.dot(p12);

    const denom = d1d1 * d2d2 - d1d2 * d1d2;

    const midPos = new THREE.Vector3().addVectors(leftWorldPos, rightWorldPos).multiplyScalar(0.5);
    const avgDir = new THREE.Vector3().addVectors(d1, d2).normalize();
    let finalPoint = new THREE.Vector3();

    if (denom > 1e-5) {
      const mu1 = (d1d2 * d2p12 - d2d2 * d1p12) / denom;
      const mu2 = (d1d1 * d2p12 - d1d2 * d1p12) / denom;

      if (mu1 > 0.05 && mu2 > 0.05 && mu1 < 10) {
        const c1 = leftWorldPos.clone().add(d1.multiplyScalar(mu1));
        const c2 = rightWorldPos.clone().add(d2.multiplyScalar(mu2));
        finalPoint.copy(c1).add(c2).multiplyScalar(0.5);
      } else {
        finalPoint.copy(midPos).add(avgDir.multiplyScalar(2.0));
      }
    } else {
      finalPoint.copy(midPos).add(avgDir.multiplyScalar(2.0));
    }

    cursorRef.current.position.copy(finalPoint);
    cursorRef.current.visible = true;
  });

  return (
    <mesh ref={cursorRef} visible={false}>
      <sphereGeometry args={[0.04, 16, 16]} />
      <meshBasicMaterial color="#fcd34d" />
    </mesh>
  );
};

const SpatialVideoPlane = () => {
  const { videoElement, avInfo, videoAspect } = useSyncedVideo();
  const textureRef = useRef<THREE.VideoTexture>(null);

  useFrame(() => {
    if (textureRef.current) {
      textureRef.current.needsUpdate = true;
    }
  });

  if (!avInfo?.has_video || !videoElement) return null;

  const height = 2.4;
  const width = height * videoAspect;

  const radius = 5;
  const thetaLength = width / radius;
  const thetaStart = Math.PI - (thetaLength / 2);

  return (
    <mesh position={[-0.6, -0.2, 3.9]} scale={[-1, 1, 1]}>
      <cylinderGeometry args={[radius, radius, height, 64, 1, true, thetaStart, thetaLength]} />
      <meshBasicMaterial side={THREE.DoubleSide} toneMapped={false}>
        <videoTexture ref={textureRef} attach="map" args={[videoElement]} colorSpace={THREE.SRGBColorSpace} />
      </meshBasicMaterial>
    </mesh>
  );
};

// Continuous Heatmap Spectrum Gradient Mapper
const getHeatColor = (norm: number): THREE.Color => {
  const t = Math.max(0, Math.min(1, norm));
  const stops = [
    { pos: 0.00, color: new THREE.Color('#4c1d95') }, // Deep violet / dark blue
    { pos: 0.18, color: new THREE.Color('#2563eb') }, // Blue
    { pos: 0.38, color: new THREE.Color('#06b6d4') }, // Cyan
    { pos: 0.58, color: new THREE.Color('#10b981') }, // Green
    { pos: 0.74, color: new THREE.Color('#eab308') }, // Yellow
    { pos: 0.88, color: new THREE.Color('#f97316') }, // Orange
    { pos: 1.00, color: new THREE.Color('#ef4444') }, // Red / Peak Hotspot
  ];

  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i].pos && t <= stops[i + 1].pos) {
      const factor = (t - stops[i].pos) / (stops[i + 1].pos - stops[i].pos);
      return stops[i].color.clone().lerp(stops[i + 1].color, factor);
    }
  }
  return stops[stops.length - 1].color.clone();
};

const AnalyticalLayers = ({ showHeatmap, showScanpath }: { showHeatmap: boolean, showScanpath: boolean }) => {
  const frames = useTelemetryStore((state) => state.frames);
  const heatmapRef = useRef<THREE.InstancedMesh>(null);
  const fixationsRef = useRef<THREE.InstancedMesh>(null);

  // We are using an 8cm Voxel Grid. This provides structured, highly-readable spatial bins.
  const VOXEL_SIZE = 0.08;

  const { heatmapData, fixationData, scanpathPoints } = useMemo(() => {
    if (!frames.length) {
      return {
        heatmapData: { count: 0, matrices: new Float32Array(), colors: new Float32Array() },
        fixationData: { count: 0, matrices: new Float32Array() },
        scanpathPoints: [] as THREE.Vector3[],
      };
    }

    // Process samples evenly across the session
    const step = Math.max(1, Math.floor(frames.length / 1500));
    const valid = frames.filter((f, i) => i % step === 0 && f.eye_tracking_valid > 0 && f.hmd_tracking_valid > 0);

    const dummy = new THREE.Object3D();
    const hmdQuat = new THREE.Quaternion();
    const hmdPos = new THREE.Vector3();
    const scanpathPts: THREE.Vector3[] = [];
    const fixations: number[] = [];
    let prevQuat = new THREE.Quaternion();

    // 3D Voxel Hash Grid
    const voxelMap = new Map<string, { pos: THREE.Vector3; intensity: number }>();

    valid.forEach(f => {
      hmdPos.set(f.hmd_pos_x, f.hmd_pos_y, f.hmd_pos_z);
      hmdQuat.set(f.hmd_rot_x || 0, f.hmd_rot_y || 0, f.hmd_rot_z || 0, f.hmd_rot_w ?? 1);

      const leftWorldPos = new THREE.Vector3(-0.032, 0, -0.075).applyQuaternion(hmdQuat).add(hmdPos);
      const rightWorldPos = new THREE.Vector3(0.032, 0, -0.075).applyQuaternion(hmdQuat).add(hmdPos);

      const leftLocalRot = new THREE.Quaternion(f.left_eye_rot_x || 0, f.left_eye_rot_y || 0, f.left_eye_rot_z || 0, f.left_eye_rot_w ?? 1).normalize();
      const rightLocalRot = new THREE.Quaternion(f.right_eye_rot_x || 0, f.right_eye_rot_y || 0, f.right_eye_rot_z || 0, f.right_eye_rot_w ?? 1).normalize();

      const leftWorldRot = hmdQuat.clone().multiply(leftLocalRot);
      const rightWorldRot = hmdQuat.clone().multiply(rightLocalRot);

      const d1 = new THREE.Vector3(0, 0, -1).applyQuaternion(leftWorldRot);
      const d2 = new THREE.Vector3(0, 0, -1).applyQuaternion(rightWorldRot);
      const p12 = new THREE.Vector3().subVectors(leftWorldPos, rightWorldPos);

      const d1d1 = d1.dot(d1); const d1d2 = d1.dot(d2); const d2d2 = d2.dot(d2);
      const d1p12 = d1.dot(p12); const d2p12 = d2.dot(p12);
      const denom = d1d1 * d2d2 - d1d2 * d1d2;

      const midPos = new THREE.Vector3().addVectors(leftWorldPos, rightWorldPos).multiplyScalar(0.5);
      const avgDir = new THREE.Vector3().addVectors(d1, d2).normalize();

      let convergencePoint = new THREE.Vector3();
      let focalDist = 2.0;

      if (denom > 1e-5) {
        const mu1 = (d1d2 * d2p12 - d2d2 * d1p12) / denom;
        const mu2 = (d1d1 * d2p12 - d1d2 * d1p12) / denom;

        if (mu1 > 0.05 && mu2 > 0.05 && mu1 < 10) {
          const c1 = leftWorldPos.clone().add(d1.multiplyScalar(mu1));
          const c2 = rightWorldPos.clone().add(d2.multiplyScalar(mu2));
          convergencePoint.copy(c1).add(c2).multiplyScalar(0.5);
          focalDist = midPos.distanceTo(convergencePoint);
        } else {
          focalDist = 2.0;
          convergencePoint.copy(midPos).add(avgDir.clone().multiplyScalar(focalDist));
        }
      } else {
        focalDist = 2.0;
        convergencePoint.copy(midPos).add(avgDir.clone().multiplyScalar(focalDist));
      }

      // Tighter beam of attention that bulges precisely at the focal depth
      const maxDistance = focalDist * 1.3;
      const raySteps = Math.max(8, Math.ceil(maxDistance / VOXEL_SIZE));
      const stepDist = maxDistance / raySteps;
      const focalSigma = Math.max(0.2, focalDist * 0.25);

      const up = new THREE.Vector3(0, 1, 0);
      if (Math.abs(avgDir.y) > 0.95) up.set(1, 0, 0);
      const rightVec = new THREE.Vector3().crossVectors(avgDir, up).normalize();
      const topVec = new THREE.Vector3().crossVectors(rightVec, avgDir).normalize();

      const addVoxelSample = (samplePos: THREE.Vector3, sampleIntensity: number) => {
        if (sampleIntensity < 0.05) return; // Drop weak edges to keep it clean

        const gx = Math.round(samplePos.x / VOXEL_SIZE);
        const gy = Math.round(samplePos.y / VOXEL_SIZE);
        const gz = Math.round(samplePos.z / VOXEL_SIZE);
        const key = `${gx},${gy},${gz}`;

        if (voxelMap.has(key)) {
          voxelMap.get(key)!.intensity += sampleIntensity;
        } else {
          voxelMap.set(key, {
            pos: new THREE.Vector3(gx * VOXEL_SIZE, gy * VOXEL_SIZE, gz * VOXEL_SIZE),
            intensity: sampleIntensity,
          });
        }
      };

      for (let s = 1; s <= raySteps; s++) {
        const curDist = s * stepDist;
        const centerPt = midPos.clone().add(avgDir.clone().multiplyScalar(curDist));

        // Depth falloff curve peaking at focal point
        const depthDelta = Math.abs(curDist - focalDist);
        const depthIntensity = Math.exp(-(depthDelta * depthDelta) / (2 * focalSigma * focalSigma));

        // Visual shape: Narrow beam that expands rapidly into a core at the focal point
        const baseRadius = curDist * 0.04;
        const focalBoost = depthIntensity * curDist * 0.08;
        const rMax = baseRadius + focalBoost;

        addVoxelSample(centerPt, depthIntensity * 1.0);

        const rInner = rMax * 0.5;
        addVoxelSample(centerPt.clone().add(rightVec.clone().multiplyScalar(rInner)), depthIntensity * 0.6);
        addVoxelSample(centerPt.clone().add(rightVec.clone().multiplyScalar(-rInner)), depthIntensity * 0.6);
        addVoxelSample(centerPt.clone().add(topVec.clone().multiplyScalar(rInner)), depthIntensity * 0.6);
        addVoxelSample(centerPt.clone().add(topVec.clone().multiplyScalar(-rInner)), depthIntensity * 0.6);

        const rOuter = rMax;
        addVoxelSample(centerPt.clone().add(rightVec.clone().multiplyScalar(rOuter)), depthIntensity * 0.25);
        addVoxelSample(centerPt.clone().add(rightVec.clone().multiplyScalar(-rOuter)), depthIntensity * 0.25);
        addVoxelSample(centerPt.clone().add(topVec.clone().multiplyScalar(rOuter)), depthIntensity * 0.25);
        addVoxelSample(centerPt.clone().add(topVec.clone().multiplyScalar(-rOuter)), depthIntensity * 0.25);
      }

      // Record Scanpath Convergence Point
      scanpathPts.push(convergencePoint.clone());

      // Fixation detection
      if (leftLocalRot.angleTo(prevQuat) < 0.08) {
        dummy.position.copy(convergencePoint);
        dummy.quaternion.identity();
        dummy.scale.set(1, 1, 1);
        dummy.updateMatrix();
        dummy.matrix.toArray(fixations, fixations.length);
      }
      prevQuat.copy(leftLocalRot);
    });

    // 95th Percentile calculation prevents rare outliers from making the rest of the map too dark
    const intensities: number[] = [];
    voxelMap.forEach(v => intensities.push(v.intensity));
    intensities.sort((a, b) => a - b);
    const p95Idx = Math.floor(intensities.length * 0.95);
    const targetMax = Math.max(1.0, intensities[p95Idx] || intensities[intensities.length - 1] || 1.0);

    const voxelCount = voxelMap.size;
    const heatmapMatrices = new Float32Array(voxelCount * 16);
    const heatmapColors = new Float32Array(voxelCount * 3);

    let idx = 0;

    voxelMap.forEach(voxel => {
      dummy.position.copy(voxel.pos);

      // Normalize density
      const norm = Math.min(1.0, voxel.intensity / targetMax);
      const curved = Math.pow(norm, 0.7);

      // *** THE SECRET TO READABILITY: DENSITY-BASED SCALING ***
      // Low attention = tiny 1.5cm speck of dust (easy to see through).
      // High attention = huge solid 8cm block.
      const sizeScale = 0.2 + (0.8 * Math.pow(norm, 0.5));
      dummy.scale.set(sizeScale, sizeScale, sizeScale);

      dummy.updateMatrix();
      dummy.matrix.toArray(heatmapMatrices, idx * 16);

      const col = getHeatColor(curved);
      heatmapColors[idx * 3] = col.r;
      heatmapColors[idx * 3 + 1] = col.g;
      heatmapColors[idx * 3 + 2] = col.b;

      idx++;
    });

    return {
      heatmapData: { count: voxelCount, matrices: heatmapMatrices, colors: heatmapColors },
      fixationData: { count: fixations.length / 16, matrices: new Float32Array(fixations) },
      scanpathPoints: scanpathPts,
    };
  }, [frames]);

  return (
    <>
      {/* 3D Discrete Voxel Heatmap Grid */}
      {showHeatmap && heatmapData.count > 0 && (
        <instancedMesh
          ref={heatmapRef}
          args={[null as any, null as any, heatmapData.count]}
        >
          {/* We use a solid Box/Cube that is 85% of the total voxel grid size.
              This leaves a tiny 15% physical gap between even the densest red blocks,
              allowing the human brain to instantly perceive depth edges! */}
          <boxGeometry args={[VOXEL_SIZE * 0.85, VOXEL_SIZE * 0.85, VOXEL_SIZE * 0.85]} />

          {/* Solid geometry with lighting restores human depth perception completely */}
          <meshStandardMaterial
            roughness={0.4}
            metalness={0.1}
          />
          <instancedBufferAttribute attach="instanceMatrix" args={[heatmapData.matrices, 16]} />
          <instancedBufferAttribute attach="instanceColor" args={[heatmapData.colors, 3]} />
        </instancedMesh>
      )}

      {/* Oculomotor Scanpath Fixations */}
      {showScanpath && fixationData.count > 0 && (
        <instancedMesh
          ref={fixationsRef}
          args={[null as any, null as any, fixationData.count]}
        >
          <sphereGeometry args={[0.025, 8, 8]} />
          <meshBasicMaterial color="#ec4899" transparent opacity={0.7} depthWrite={false} />
          <instancedBufferAttribute attach="instanceMatrix" args={[fixationData.matrices, 16]} />
        </instancedMesh>
      )}

      {/* Oculomotor Saccadic Scanpath Trajectory */}
      {showScanpath && scanpathPoints.length > 1 && (
        <Line points={scanpathPoints} color="#f472b6" lineWidth={1.5} transparent opacity={0.35} />
      )}
    </>
  );
};

export const SpatialViewer = () => {
  const [showHeatmap, setShowHeatmap] = useState(true);
  const [showScanpath, setShowScanpath] = useState(true);
  const [showLivePoR, setShowLivePoR] = useState(true);
  const [showVideo, setShowVideo] = useState(true);

  return (
    <div className="w-full h-full bg-slate-900 rounded-xl overflow-hidden shadow-inner relative border border-research-border">

      {/* UI Overlay for Layer Toggles & Heatmap Legend */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-2 pointer-events-auto">
        <div className="bg-slate-950/80 backdrop-blur-md border border-white/20 p-3 rounded-lg shadow-xl w-60">
          <div className="text-[10px] font-bold text-white/70 uppercase tracking-widest mb-2 flex items-center gap-1.5">
            <Layers className="w-3.5 h-3.5 text-blue-400" /> Spatial Overlays
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowHeatmap(!showHeatmap)}
              className={`flex flex-1 items-center gap-2 w-full text-left px-3 py-1.5 rounded text-xs transition-colors ${showHeatmap ? 'bg-red-500/20 text-red-300 border-red-400/30 border' : 'text-white/60 hover:bg-white/5 border border-transparent'}`}
            >
              <Eye className="w-3.5 h-3.5" /> Volumetric Heatmap
            </button>
            <InfoTooltip id="spatial.heatmap" side="left" className="info-trigger-dark" />
          </div>

          {showHeatmap && (
            <div className="px-1 mt-2 mb-2">
              <div className="text-[9px] font-medium text-white/70 mb-1">
                Gaze Density / Attention Intensity
              </div>
              <div
                className="h-2 w-full rounded-full shadow-inner"
                style={{ background: 'linear-gradient(to right, #4c1d95, #2563eb, #06b6d4, #10b981, #eab308, #f97316, #ef4444)' }}
              />
              <div className="flex justify-between text-[8px] font-mono text-white/50 uppercase mt-0.5">
                <span>Low (Void)</span>
                <span>Focal Peak (Hotspot)</span>
              </div>
            </div>
          )}

          <div className="flex items-center gap-1 mt-1">
            <button
              onClick={() => setShowScanpath(!showScanpath)}
              className={`flex flex-1 items-center gap-2 w-full text-left px-3 py-1.5 rounded text-xs transition-colors ${showScanpath ? 'bg-pink-500/20 text-pink-300 border-pink-400/30 border' : 'text-white/60 hover:bg-white/5 border border-transparent'}`}
            >
              <Activity className="w-3.5 h-3.5" /> Oculomotor Scanpath
            </button>
            <InfoTooltip id="spatial.scanpath" side="left" className="info-trigger-dark" />
          </div>

          <div className="flex items-center gap-1 mt-1">
            <button
              onClick={() => setShowLivePoR(!showLivePoR)}
              className={`flex flex-1 items-center gap-2 w-full text-left px-3 py-1.5 rounded text-xs transition-colors ${showLivePoR ? 'bg-amber-500/20 text-amber-300 border-amber-400/30 border' : 'text-white/60 hover:bg-white/5 border border-transparent'}`}
            >
              <Crosshair className="w-3.5 h-3.5" /> Live Point of Regard
            </button>
            <InfoTooltip id="spatial.por" side="left" className="info-trigger-dark" />
          </div>
          <div className="flex items-center gap-1 mt-1">
            <button
              onClick={() => setShowVideo(!showVideo)}
              className={`flex flex-1 items-center gap-2 w-full text-left px-3 py-1.5 rounded text-xs transition-colors ${showVideo ? 'bg-indigo-500/20 text-indigo-300 border-indigo-400/30 border' : 'text-white/60 hover:bg-white/5 border border-transparent'}`}
            >
              <Video className="w-3.5 h-3.5" /> 3D Video Plane
            </button>
            <InfoTooltip id="spatial.video" side="left" className="info-trigger-dark" />
          </div>
        </div>
      </div>

      <Canvas camera={{ position: [0, 1.6, 2.5], fov: 60 }}>
        <ambientLight intensity={0.6} />
        {/* Slightly stronger lighting to highlight the edges of the voxels */}
        <directionalLight position={[5, 10, 7]} intensity={1.2} />
        <directionalLight position={[-5, 5, -7]} intensity={0.4} />
        <Grid args={[10, 10]} cellColor="#334155" sectionColor="#1e293b" fadeDistance={10} />

        <VRRig />
        <LivePoRCursor visible={showLivePoR} />
        {showVideo && <SpatialVideoPlane />}
        <AnalyticalLayers showHeatmap={showHeatmap} showScanpath={showScanpath} />

        <OrbitControls target={[0, 1.0, 0]} />
      </Canvas>
    </div>
  );
};
