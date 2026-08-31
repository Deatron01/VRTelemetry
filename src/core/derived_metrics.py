import math


def _rotate_forward(qx: float, qy: float, qz: float, qw: float) -> tuple[float, float, float]:
    """Rotates the fixed forward vector (0,0,-1) by a quaternion."""
    fx = -2 * (qx * qz + qw * qy)
    fy = -2 * (qy * qz - qw * qx)
    fz = -(1 - 2 * (qx * qx + qy * qy))
    return fx, fy, fz


def compute_binocular_focal_distance(frame) -> float:
    """
    Vergence-based focal distance from binocular eye pose — same closest-point-between
    -two-rays geometry the frontend heatmap already uses for visualization, computed here
    at capture time so it's part of the recorded dataset itself. Returns -1.0 if eye
    tracking isn't valid this frame (not 0.0, which would look like "focused at your face").
    """
    if frame.eye_tracking_valid <= 0:
        return -1.0

    lx, ly, lz = frame.left_eye_pos_x, frame.left_eye_pos_y, frame.left_eye_pos_z
    rx, ry, rz = frame.right_eye_pos_x, frame.right_eye_pos_y, frame.right_eye_pos_z
    d1 = _rotate_forward(
        frame.left_eye_rot_x, frame.left_eye_rot_y, frame.left_eye_rot_z, frame.left_eye_rot_w
    )
    d2 = _rotate_forward(
        frame.right_eye_rot_x, frame.right_eye_rot_y, frame.right_eye_rot_z, frame.right_eye_rot_w
    )

    p12 = (lx - rx, ly - ry, lz - rz)
    d1d1 = sum(a * a for a in d1)
    d2d2 = sum(a * a for a in d2)
    d1d2 = sum(a * b for a, b in zip(d1, d2))
    d1p12 = sum(a * b for a, b in zip(d1, p12))
    d2p12 = sum(a * b for a, b in zip(d2, p12))
    denom = d1d1 * d2d2 - d1d2 * d1d2

    mid = ((lx + rx) / 2, (ly + ry) / 2, (lz + rz) / 2)

    if abs(denom) < 1e-6:
        return 2.0  # near-parallel gaze rays — matches the frontend's far-plane fallback

    mu1 = (d1d2 * d2p12 - d2d2 * d1p12) / denom
    mu2 = (d1d1 * d2p12 - d1d2 * d1p12) / denom
    if not (0.05 < mu1 < 10 and 0.05 < mu2 < 10):
        return 2.0

    c1 = (lx + d1[0] * mu1, ly + d1[1] * mu1, lz + d1[2] * mu1)
    c2 = (rx + d2[0] * mu2, ry + d2[1] * mu2, rz + d2[2] * mu2)
    conv = ((c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2, (c1[2] + c2[2]) / 2)

    dx, dy, dz = conv[0] - mid[0], conv[1] - mid[1], conv[2] - mid[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def compute_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)
