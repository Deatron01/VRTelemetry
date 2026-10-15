# src/backends/desktop_mirror.py
"""Capture the Windows desktop and submit it as an OpenXR CompositionLayerQuad.

When VRTelemetry runs as the scene app via ``openxr_headless``, the compositor
has nothing to display — SteamVR / Vive Streaming's mirror window is black.
This module captures the primary monitor via DXGI Desktop Duplication and
uploads each frame into an OpenXR swapchain, which is then handed back as a
quad layer for ``xrEndFrame``.  SteamVR composites it into its mirror window,
so the operator glancing at the PC screen sees the live desktop.

All COM / DXGI / D3D11 interaction is pure ctypes — no new native
dependencies, matching the pattern already established in
``openxr_headless._create_d3d11_binding()``.

The class is intentionally self-contained: ``OpenXRHeadlessBackend`` calls
``setup()``, ``update_and_get_layer()`` per frame, and ``destroy()`` at
shutdown.  A failure at any stage logs and returns ``None``, so the recording
is never affected.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes
import logging
import platform
from typing import TYPE_CHECKING, Any

import xr

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DXGI / D3D11 constants (subset needed for Desktop Duplication)
# ---------------------------------------------------------------------------

# DXGI_FORMAT_B8G8R8A8_UNORM — the native pixel format of Desktop Duplication.
DXGI_FORMAT_B8G8R8A8_UNORM: int = 87


# COM IIDs as ctypes GUID structures
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _make_guid(d1: int, d2: int, d3: int, d4: bytes) -> _GUID:
    arr = (ctypes.c_ubyte * 8)(*d4)
    return _GUID(d1, d2, d3, arr)


# {db6f6ddb-ac77-4e88-8253-819df9bbf140}  IDXGIDevice
IID_IDXGIDevice = _make_guid(0xDB6F6DDB, 0xAC77, 0x4E88, b"\x82\x53\x81\x9d\xf9\xbb\xf1\x40")

# {770aae78-f26f-4dba-a829-253c83d1b387}  IDXGIAdapter1
IID_IDXGIAdapter1 = _make_guid(0x770AAE78, 0xF26F, 0x4DBA, b"\xa8\x29\x25\x3c\x83\xd1\xb3\x87")

# {00cddea8-939b-4b83-a340-a685226666cc}  IDXGIOutput1
IID_IDXGIOutput1 = _make_guid(0x00CDDEA8, 0x939B, 0x4B83, b"\xa3\x40\xa6\x85\x22\x66\x66\xcc")

# D3D11 resource dimension for Texture2D
D3D11_RESOURCE_DIMENSION_TEXTURE2D: int = 3

# Timeout for AcquireNextFrame (milliseconds). 0 = non-blocking.
_ACQUIRE_TIMEOUT_MS: int = 0

# DXGI_ERROR_WAIT_TIMEOUT (0x887A0027) — no new frame available yet.
_DXGI_ERROR_WAIT_TIMEOUT: int = 0x887A0027 & 0xFFFFFFFF

# DXGI_ERROR_ACCESS_LOST — desktop switch, UAC, screen saver, etc.
_DXGI_ERROR_ACCESS_LOST: int = 0x887A0026 & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Minimal COM vtable wrappers — just the methods we need
# ---------------------------------------------------------------------------
# These are not full COM bindings. Each wrapper calls through the vtable at a
# known slot index using ctypes.WINFUNCTYPE, which is exactly how the Win32
# ABI dispatches COM calls (ptr -> vtable[slot](self, ...)).
# ---------------------------------------------------------------------------


def _winfunctype(restype: object, *argtypes: object) -> Any:
    """``ctypes.WINFUNCTYPE``, looked up when called.

    It exists only on Windows, so a module-level reference would fail the
    import -- and the type check, which runs on Linux in CI -- everywhere else.
    """
    return getattr(ctypes, "WINFUNCTYPE")(restype, *argtypes)  # noqa: B009


def _com_release(punk: ctypes.c_void_p) -> int:
    """IUnknown::Release (vtable slot 2)."""
    vt = ctypes.cast(
        ctypes.cast(punk, ctypes.POINTER(ctypes.c_void_p))[0],
        ctypes.POINTER(ctypes.c_void_p),
    )
    fn = _winfunctype(ctypes.c_ulong, ctypes.c_void_p)(vt[2])
    return fn(punk)


def _com_qi(punk: ctypes.c_void_p, iid: _GUID) -> ctypes.c_void_p:
    """IUnknown::QueryInterface (vtable slot 0). Raises on failure."""
    vt = ctypes.cast(
        ctypes.cast(punk, ctypes.POINTER(ctypes.c_void_p))[0],
        ctypes.POINTER(ctypes.c_void_p),
    )
    fn = _winfunctype(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
    )(vt[0])
    out = ctypes.c_void_p()
    hr = fn(punk, ctypes.byref(iid), ctypes.byref(out))
    if hr < 0:
        raise OSError(f"QueryInterface failed: HRESULT {hex(hr & 0xFFFFFFFF)}")
    return out


# ---------------------------------------------------------------------------
# DXGI_OUTDUPL_DESC
# ---------------------------------------------------------------------------


class _DXGI_MODE_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("RefreshRate_Numerator", ctypes.c_uint),
        ("RefreshRate_Denominator", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("ScanlineOrdering", ctypes.c_uint),
        ("Scaling", ctypes.c_uint),
    ]


class _DXGI_OUTDUPL_DESC(ctypes.Structure):
    _fields_ = [
        ("ModeDesc", _DXGI_MODE_DESC),
        ("Rotation", ctypes.c_uint),
        ("DesktopImageInSystemMemory", ctypes.c_int),
    ]


# ---------------------------------------------------------------------------
# DXGI_OUTDUPL_FRAME_INFO — needed by AcquireNextFrame
# ---------------------------------------------------------------------------


class _DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [
        ("LastPresentTime", ctypes.c_longlong),
        ("LastMouseUpdateTime", ctypes.c_longlong),
        ("AccumulatedFrames", ctypes.c_uint),
        ("RectsCoalesced", ctypes.c_int),
        ("ProtectedContentMaskedOut", ctypes.c_int),
        ("PointerPosition_Visible", ctypes.c_int),
        ("PointerPosition_x", ctypes.c_long),
        ("PointerPosition_y", ctypes.c_long),
        ("PointerShapeBufferSize", ctypes.c_uint),
        ("TotalMetadataBufferSize", ctypes.c_uint),
    ]


# ---------------------------------------------------------------------------
# D3D11_TEXTURE2D_DESC — needed to read dimensions of the duplicated texture
# ---------------------------------------------------------------------------


class _D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ("Width", ctypes.c_uint),
        ("Height", ctypes.c_uint),
        ("MipLevels", ctypes.c_uint),
        ("ArraySize", ctypes.c_uint),
        ("Format", ctypes.c_uint),
        ("SampleDesc_Count", ctypes.c_uint),
        ("SampleDesc_Quality", ctypes.c_uint),
        ("Usage", ctypes.c_uint),
        ("BindFlags", ctypes.c_uint),
        ("CPUAccessFlags", ctypes.c_uint),
        ("MiscFlags", ctypes.c_uint),
    ]


# ---------------------------------------------------------------------------
# DesktopMirrorLayer
# ---------------------------------------------------------------------------


class DesktopMirrorLayer:
    """Captures the primary desktop and provides an ``XrCompositionLayerQuad``.

    Lifecycle::

        mirror = DesktopMirrorLayer()
        mirror.setup(session, d3d_device, d3d_context, space)
        # — per frame —
        layer = mirror.update_and_get_layer()
        # — shutdown —
        mirror.destroy()

    If setup fails (no monitor, secure desktop, GPU mismatch), ``setup``
    raises.  If a per-frame capture fails, ``update_and_get_layer`` returns
    ``None`` and the caller falls back to zero layers.
    """

    def __init__(self) -> None:
        # DXGI duplication handles (COM pointers stored as c_void_p)
        self._duplication: ctypes.c_void_p | None = None
        self._dxgi_device: ctypes.c_void_p | None = None
        self._adapter: ctypes.c_void_p | None = None
        self._output: ctypes.c_void_p | None = None
        self._output1: ctypes.c_void_p | None = None

        # OpenXR handles
        self._swapchain: xr.Swapchain | None = None
        self._swapchain_images: list[xr.SwapchainImageD3D11KHR] = []

        # D3D11 context for CopyResource
        self._d3d_context: ctypes.c_void_p | None = None

        # Desktop dimensions
        self._width: int = 0
        self._height: int = 0

        # The pre-built layer (updated each frame)
        self._layer: xr.CompositionLayerQuad | xr.CompositionLayerCylinderKHR | None = None
        self._space: xr.Space | None = None

        # Whether we have a valid frame in the swapchain (after first
        # successful capture)
        self._has_content: bool = False

        # Tracks whether the duplication was lost and needs re-creation
        self._duplication_lost: bool = False

    def setup(
        self,
        session: xr.Session,
        d3d_device: ctypes.c_void_p,
        d3d_context: ctypes.c_void_p,
        space: xr.Space,
        use_cylinder: bool = False,
    ) -> None:
        """Initialise DXGI duplication and the OpenXR swapchain.

        Args:
            session: The active OpenXR session (must have a D3D11 binding).
            d3d_device: Raw ``ID3D11Device*`` from ``_create_d3d11_binding``.
            d3d_context: Raw ``ID3D11DeviceContext*``.
            space: Reference space for the quad layer placement.

        Raises:
            OSError: If any DXGI / COM call fails.
            RuntimeError: If the swapchain cannot be created.
        """
        if platform.system() != "Windows":
            raise NotImplementedError("Desktop mirroring requires Windows.")

        self._d3d_context = d3d_context
        self._space = space

        # ------------------------------------------------------------------
        # 1. Walk the COM chain: Device → DXGIDevice → Adapter → Output → Output1
        # ------------------------------------------------------------------
        self._dxgi_device = _com_qi(d3d_device, IID_IDXGIDevice)

        # IDXGIDevice::GetParent → IDXGIAdapter (vtable slot 9 = GetAdapter for
        # IDXGIDevice, but GetParent at slot 6 of IDXGIObject is more reliable
        # across versions).  We use GetAdapter at vtable slot 7 (0-based) of
        # IDXGIDevice.
        # Actually: IDXGIDevice vtable:
        #   0 QI, 1 AddRef, 2 Release, 3 SetPrivateData, 4 SetPrivateDataInterface,
        #   5 GetPrivateData, 6 GetParent, 7 EnumAdapters(n/a), ...
        # IDXGIDevice inherits IDXGIObject. GetAdapter is at slot 10.
        #   IDXGIObject: 0-6 (QI, AddRef, Release, SetPrivateData,
        #                     SetPrivateDataInterface, GetPrivateData, GetParent)
        #   IDXGIDevice: 7 GetAdapter, 8 CreateSurface, 9 QueryResourceResidency,
        #                10 SetGPUThreadPriority, 11 GetGPUThreadPriority

        vt = ctypes.cast(
            ctypes.cast(self._dxgi_device, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        # IDXGIDevice::GetAdapter (slot 7)
        get_adapter_fn = _winfunctype(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
        )(vt[7])
        self._adapter = ctypes.c_void_p()
        hr = get_adapter_fn(self._dxgi_device, ctypes.byref(self._adapter))
        if hr < 0:
            raise OSError(f"IDXGIDevice::GetAdapter failed: HRESULT {hex(hr & 0xFFFFFFFF)}")

        # IDXGIAdapter::EnumOutputs(0, ...) — slot 7 of IDXGIAdapter
        # IDXGIAdapter inherits IDXGIObject (slots 0-6).
        # IDXGIAdapter: 7 EnumOutputs, 8 GetDesc, 9 CheckInterfaceSupport
        vt_adapter = ctypes.cast(
            ctypes.cast(self._adapter, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        enum_outputs_fn = _winfunctype(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )(vt_adapter[7])
        self._output = ctypes.c_void_p()
        hr = enum_outputs_fn(self._adapter, 0, ctypes.byref(self._output))
        if hr < 0:
            raise OSError(
                f"IDXGIAdapter::EnumOutputs(0) failed: HRESULT {hex(hr & 0xFFFFFFFF)}. "
                f"No monitor attached?"
            )

        # QI for IDXGIOutput1
        self._output1 = _com_qi(self._output, IID_IDXGIOutput1)

        # ------------------------------------------------------------------
        # 2. Create Desktop Duplication
        # ------------------------------------------------------------------
        self._create_duplication(d3d_device)

        # ------------------------------------------------------------------
        # 3. Create OpenXR swapchain
        # ------------------------------------------------------------------
        swapchain_info = xr.SwapchainCreateInfo(
            create_flags=xr.SwapchainCreateFlags.STATIC_IMAGE_BIT,
            usage_flags=(
                xr.SwapchainUsageFlags.COLOR_ATTACHMENT_BIT
                | xr.SwapchainUsageFlags.TRANSFER_DST_BIT
            ),
            format=DXGI_FORMAT_B8G8R8A8_UNORM,
            sample_count=1,
            width=self._width,
            height=self._height,
            face_count=1,
            array_size=1,
            mip_count=1,
        )
        self._swapchain = xr.create_swapchain(session, swapchain_info)

        images = xr.enumerate_swapchain_images(self._swapchain, xr.SwapchainImageD3D11KHR)
        self._swapchain_images = list(images)
        if not self._swapchain_images:
            raise RuntimeError("OpenXR returned zero swapchain images.")

        logger.info(
            f"Desktop mirror swapchain created: {self._width}x{self._height}, "
            f"{len(self._swapchain_images)} image(s)."
        )

        # ------------------------------------------------------------------
        # 4. Pre-build the quad layer (sub_image and pose are constant)
        # ------------------------------------------------------------------
        aspect = self._width / max(self._height, 1)
        quad_height = 2.0  # metres
        quad_width = quad_height * aspect

        sub_img = xr.SwapchainSubImage(
            swapchain=self._swapchain,
            image_rect=xr.Rect2Di(
                offset=xr.Offset2Di(x=0, y=0),
                extent=xr.Extent2Di(width=self._width, height=self._height),
            ),
            image_array_index=0,
        )
        flags = xr.CompositionLayerFlags.BLEND_TEXTURE_SOURCE_ALPHA_BIT

        if use_cylinder:
            pose_cylinder = xr.Posef(
                orientation=xr.Quaternionf(x=0.0, y=0.0, z=0.0, w=1.0),
                position=xr.Vector3f(x=0.0, y=1.0, z=0.0),  # Cylinder center at y=1.0
            )
            self._layer = xr.CompositionLayerCylinderKHR(
                layer_flags=flags,
                space=space,
                eye_visibility=xr.EyeVisibility.BOTH,
                sub_image=sub_img,
                pose=pose_cylinder,
                radius=2.5,  # surface will be 2.5m in front
                central_angle=quad_width / 2.5,  # arc length = radius * angle
                aspect_ratio=aspect,
            )
        else:
            pose_quad = xr.Posef(
                orientation=xr.Quaternionf(x=0.0, y=0.0, z=0.0, w=1.0),
                position=xr.Vector3f(x=0.0, y=0.0, z=-2.5),  # quad center at z=-2.5
            )
            self._layer = xr.CompositionLayerQuad(
                layer_flags=flags,
                space=space,
                eye_visibility=xr.EyeVisibility.BOTH,
                sub_image=sub_img,
                pose=pose_quad,
                size=xr.Extent2Df(width=quad_width, height=quad_height),
            )

    def _create_duplication(self, d3d_device: ctypes.c_void_p) -> None:
        """Call ``IDXGIOutput1::DuplicateOutput`` and read the desktop size.

        Separated so it can be retried when access is lost (UAC, screen saver,
        desktop switch).
        """
        if self._output1 is None:
            raise OSError("DuplicateOutput called before IDXGIOutput1 was acquired")
        # IDXGIOutput1 inherits IDXGIOutput which inherits IDXGIObject (0-6).
        # IDXGIOutput: 7 GetDesc, 8 GetDisplayModeList, 9 FindClosestMatchingMode,
        #              10 WaitForVBlank, 11 TakeOwnership, 12 ReleaseOwnership,
        #              13 GetGammaControlCapabilities, 14 SetGammaControl,
        #              15 GetGammaControl, 16 SetDisplaySurface,
        #              17 GetDisplaySurfaceData, 18 GetFrameStatistics
        # IDXGIOutput1: 19 GetDisplayModeList1, 20 FindClosestMatchingMode1,
        #               21 GetDisplaySurfaceData1, 22 DuplicateOutput
        vt_out1 = ctypes.cast(
            ctypes.cast(self._output1, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        duplicate_output_fn = _winfunctype(
            ctypes.c_long,
            ctypes.c_void_p,  # this (IDXGIOutput1*)
            ctypes.c_void_p,  # pDevice (IUnknown*)
            ctypes.POINTER(ctypes.c_void_p),  # ppOutputDuplication
        )(vt_out1[22])
        self._duplication = ctypes.c_void_p()
        hr = duplicate_output_fn(self._output1, d3d_device, ctypes.byref(self._duplication))
        if hr < 0:
            raise OSError(f"IDXGIOutput1::DuplicateOutput failed: HRESULT {hex(hr & 0xFFFFFFFF)}")

        # Read DXGI_OUTDUPL_DESC to get dimensions.
        # IDXGIOutputDuplication: inherits IDXGIObject (0-6)
        # 7 GetDesc, 8 AcquireNextFrame, 9 GetFrameDirtyRects,
        # 10 GetFrameMoveRects, 11 GetFramePointerShape, 12 MapDesktopSurface,
        # 13 UnMapDesktopSurface, 14 ReleaseFrame
        vt_dup = ctypes.cast(
            ctypes.cast(self._duplication, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        get_desc_fn = _winfunctype(None, ctypes.c_void_p, ctypes.POINTER(_DXGI_OUTDUPL_DESC))(
            vt_dup[7]
        )
        desc = _DXGI_OUTDUPL_DESC()
        get_desc_fn(self._duplication, ctypes.byref(desc))

        self._width = desc.ModeDesc.Width
        self._height = desc.ModeDesc.Height
        self._duplication_lost = False
        logger.info(
            f"DXGI Desktop Duplication active: {self._width}x{self._height} "
            f"(format {desc.ModeDesc.Format})"
        )

    # ------------------------------------------------------------------
    # Per-frame capture
    # ------------------------------------------------------------------

    def update_and_get_layer(
        self,
    ) -> xr.CompositionLayerQuad | xr.CompositionLayerCylinderKHR | None:
        """Capture the latest desktop frame and return the quad layer.

        Returns ``None`` if no frame could be captured (timeout, lost, error),
        **unless** a previous frame is still in the swapchain — in that case
        the stale-but-valid quad is returned so the mirror window stays lit.
        """
        if self._duplication is None or self._layer is None:
            return None

        if self._duplication_lost:
            return None

        # -- AcquireNextFrame --------------------------------------------------
        vt_dup = ctypes.cast(
            ctypes.cast(self._duplication, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        # Slot 8: AcquireNextFrame(UINT TimeoutInMilliseconds,
        #                          DXGI_OUTDUPL_FRAME_INFO*, IDXGIResource**)
        acquire_fn = _winfunctype(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.POINTER(_DXGI_OUTDUPL_FRAME_INFO),
            ctypes.POINTER(ctypes.c_void_p),
        )(vt_dup[8])

        frame_info = _DXGI_OUTDUPL_FRAME_INFO()
        desktop_resource = ctypes.c_void_p()
        hr = acquire_fn(
            self._duplication,
            _ACQUIRE_TIMEOUT_MS,
            ctypes.byref(frame_info),
            ctypes.byref(desktop_resource),
        )

        hr_unsigned = hr & 0xFFFFFFFF if hr < 0 else hr

        if hr_unsigned == _DXGI_ERROR_WAIT_TIMEOUT:
            # No new desktop frame — return the last good layer if we have one.
            return self._layer if self._has_content else None

        if hr_unsigned == _DXGI_ERROR_ACCESS_LOST:
            logger.warning("Desktop duplication access lost (screen saver / UAC / desktop switch).")
            self._duplication_lost = True
            return self._layer if self._has_content else None

        if hr < 0:
            logger.debug(f"AcquireNextFrame failed: HRESULT {hex(hr_unsigned)}")
            return self._layer if self._has_content else None

        # We have a new desktop frame. Copy it into the swapchain.
        try:
            self._copy_to_swapchain(desktop_resource)
            self._has_content = True
        except Exception:  # a mirror frame must never fail a recording
            logger.debug("Failed to copy desktop frame to swapchain.", exc_info=True)
        finally:
            # Always release the acquired frame and the resource
            _com_release(desktop_resource)
            # Slot 14: ReleaseFrame()
            release_frame_fn = _winfunctype(ctypes.c_long, ctypes.c_void_p)(vt_dup[14])
            release_frame_fn(self._duplication)

        return self._layer if self._has_content else None

    def _copy_to_swapchain(self, desktop_resource: ctypes.c_void_p) -> None:
        """Copy the acquired desktop texture into the OpenXR swapchain image.

        Uses ``ID3D11DeviceContext::CopyResource`` — a single GPU-side blit,
        the cheapest possible path for identical-format, identical-size textures.
        """
        if not self._swapchain or not self._swapchain_images or not self._d3d_context:
            return

        # QI the DXGI resource for ID3D11Texture2D.  The IID is
        # {6f15aaf2-d208-4e89-9ab4-489535d34f9c}.
        IID_ID3D11Texture2D = _make_guid(
            0x6F15AAF2, 0xD208, 0x4E89, b"\x9a\xb4\x48\x95\x35\xd3\x4f\x9c"
        )
        src_tex = _com_qi(desktop_resource, IID_ID3D11Texture2D)

        try:
            # Acquire the swapchain image
            idx = xr.acquire_swapchain_image(self._swapchain, xr.SwapchainImageAcquireInfo())
            xr.wait_swapchain_image(
                self._swapchain, xr.SwapchainImageWaitInfo(timeout=xr.INFINITE_DURATION)
            )

            # The swapchain image's D3D11 texture pointer
            dst_tex = self._swapchain_images[idx].texture
            dst_ptr = ctypes.cast(dst_tex, ctypes.c_void_p)

            # ID3D11DeviceContext::CopyResource (vtable slot 47)
            # void CopyResource(ID3D11Resource* pDstResource, ID3D11Resource* pSrcResource)
            vt_ctx = ctypes.cast(
                ctypes.cast(self._d3d_context, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            copy_resource_fn = _winfunctype(
                None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
            )(vt_ctx[47])
            copy_resource_fn(self._d3d_context, dst_ptr, src_tex)

            xr.release_swapchain_image(self._swapchain, xr.SwapchainImageReleaseInfo())

        finally:
            _com_release(src_tex)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def destroy(self) -> None:
        """Release all DXGI and OpenXR resources.

        Safe to call multiple times; each handle is cleared as it is released.
        """
        if self._swapchain is not None:
            with contextlib.suppress(xr.XrException):
                xr.destroy_swapchain(self._swapchain)
            self._swapchain = None
            self._swapchain_images = []

        for name in ("_duplication", "_output1", "_output", "_adapter", "_dxgi_device"):
            punk = getattr(self, name, None)
            if punk is not None:
                # COM release during teardown: nothing useful to do on failure.
                with contextlib.suppress(Exception):
                    _com_release(punk)
                setattr(self, name, None)

        self._layer = None
        self._has_content = False
        self._d3d_context = None
        self._space = None
        logger.info("Desktop mirror layer destroyed.")
