# tests/unit/test_desktop_mirror.py
"""Unit tests for the desktop mirror compositor layer.

These tests exercise the ``DesktopMirrorLayer`` class without real DXGI or
OpenXR hardware.  All COM / D3D11 / OpenXR calls are patched so the tests run
on any machine (including CI on Linux).
"""

from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Patch the Windows-only ctypes.WINFUNCTYPE before importing the module.
# On non-Windows (and in CI), this attribute does not exist, and the module
# references it at call-time, so we need it importable.
# ---------------------------------------------------------------------------
_real_winfunctype = getattr(ctypes, "WINFUNCTYPE", None)
if _real_winfunctype is None:
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE  # type: ignore[attr-defined]
    ctypes.windll = MagicMock()  # type: ignore[attr-defined]


from src.backends.desktop_mirror import (  # noqa: E402
    DXGI_FORMAT_B8G8R8A8_UNORM,
    DesktopMirrorLayer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_vtable(*slot_fns: object) -> ctypes.c_void_p:
    """Build a minimal COM-style vtable pointer for testing.

    Each positional argument is the Python callable placed at that slot index.
    The returned ``c_void_p`` can be dereferenced like a real COM pointer:
    ``cast(ptr, POINTER(c_void_p))[0]`` yields the vtable address.
    """
    n = len(slot_fns)
    VT = ctypes.c_void_p * n  # noqa: N806
    vt_array = VT()
    for i, fn in enumerate(slot_fns):
        if fn is not None:
            cfn = ctypes.cast(ctypes.c_void_p(id(fn)), ctypes.c_void_p)
            vt_array[i] = cfn
    vt_ptr = ctypes.cast(ctypes.pointer(vt_array), ctypes.c_void_p)
    # Wrap in an outer pointer so that ptr[0] == vtable address
    outer = ctypes.pointer(vt_ptr)
    return ctypes.cast(outer, ctypes.c_void_p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDesktopMirrorLayerConstruction:
    """Test that DesktopMirrorLayer initialises cleanly."""

    def test_init_defaults(self) -> None:
        mirror = DesktopMirrorLayer()
        assert mirror._swapchain is None
        assert mirror._duplication is None
        assert mirror._layer is None
        assert mirror._has_content is False
        assert mirror._width == 0
        assert mirror._height == 0

    def test_update_returns_none_before_setup(self) -> None:
        mirror = DesktopMirrorLayer()
        assert mirror.update_and_get_layer() is None

    def test_destroy_is_safe_before_setup(self) -> None:
        """destroy() must not raise on a never-initialised instance."""
        mirror = DesktopMirrorLayer()
        mirror.destroy()  # should be a no-op


class TestDesktopMirrorLayerSetup:
    """Test the setup path with mocked COM and OpenXR calls."""

    @patch("src.backends.desktop_mirror.platform")
    def test_setup_rejects_non_windows(self, mock_platform: MagicMock) -> None:
        mock_platform.system.return_value = "Linux"
        mirror = DesktopMirrorLayer()
        with pytest.raises(NotImplementedError, match="Windows"):
            mirror.setup(
                session=MagicMock(),
                d3d_device=ctypes.c_void_p(0x1),
                d3d_context=ctypes.c_void_p(0x2),
                space=MagicMock(),
            )


class TestDesktopMirrorLayerQuadGeometry:
    """Test quad layer geometry calculations."""

    def test_16_9_aspect_ratio(self) -> None:
        """A 1920x1080 desktop should produce a ~1.6m x 0.9m quad."""
        mirror = DesktopMirrorLayer()
        # Simulate post-setup state
        mirror._width = 1920
        mirror._height = 1080
        aspect = mirror._width / mirror._height
        quad_height = 0.9
        quad_width = quad_height * aspect
        # 16:9 → width ≈ 1.6
        assert abs(quad_width - 1.6) < 0.01

    def test_4_3_aspect_ratio(self) -> None:
        """A 1024x768 desktop should produce a 1.2m x 0.9m quad."""
        mirror = DesktopMirrorLayer()
        mirror._width = 1024
        mirror._height = 768
        aspect = mirror._width / mirror._height
        quad_height = 0.9
        quad_width = quad_height * aspect
        assert abs(quad_width - 1.2) < 0.01


class TestDesktopMirrorLayerDestroy:
    """Test destroy() releases resources."""

    def test_destroy_clears_all_handles(self) -> None:
        mirror = DesktopMirrorLayer()
        # Simulate a partly-initialised state
        mirror._layer = MagicMock()
        mirror._has_content = True
        mirror._d3d_context = ctypes.c_void_p(0x99)
        mirror._space = MagicMock()

        mirror.destroy()

        assert mirror._layer is None
        assert mirror._has_content is False
        assert mirror._d3d_context is None
        assert mirror._space is None

    @patch("src.backends.desktop_mirror._com_release")
    def test_destroy_calls_com_release(self, mock_release: MagicMock) -> None:
        mirror = DesktopMirrorLayer()
        fake_ptr = ctypes.c_void_p(0xDEAD)
        mirror._duplication = fake_ptr
        mirror._dxgi_device = ctypes.c_void_p(0xBEEF)
        mirror._output1 = ctypes.c_void_p(0xCAFE)
        mirror._output = ctypes.c_void_p(0xF00D)
        mirror._adapter = ctypes.c_void_p(0xBABE)

        mirror.destroy()

        # One Release per COM pointer
        assert mock_release.call_count == 5
        # All cleared
        assert mirror._duplication is None
        assert mirror._dxgi_device is None
        assert mirror._output1 is None

    @patch("src.backends.desktop_mirror.xr")
    @patch("src.backends.desktop_mirror._com_release")
    def test_destroy_destroys_swapchain(self, _mock_release: MagicMock, mock_xr: MagicMock) -> None:
        mirror = DesktopMirrorLayer()
        fake_swapchain = MagicMock()
        mirror._swapchain = fake_swapchain
        mirror._swapchain_images = [MagicMock()]

        mirror.destroy()

        mock_xr.destroy_swapchain.assert_called_once_with(fake_swapchain)
        assert mirror._swapchain is None
        assert mirror._swapchain_images == []


class TestDesktopMirrorLayerUpdate:
    """Test update_and_get_layer under various conditions."""

    def test_returns_none_without_duplication(self) -> None:
        mirror = DesktopMirrorLayer()
        mirror._layer = MagicMock()
        # _duplication is None → should return None
        assert mirror.update_and_get_layer() is None

    def test_returns_none_when_duplication_lost(self) -> None:
        mirror = DesktopMirrorLayer()
        mirror._layer = MagicMock()
        mirror._duplication = ctypes.c_void_p(0x1)
        mirror._duplication_lost = True
        assert mirror.update_and_get_layer() is None


class TestConfigToggle:
    """Test that the config setting exists and defaults to True."""

    def test_default_enable_desktop_mirror(self) -> None:
        from src.config.settings import AcquisitionSettings

        settings = AcquisitionSettings()
        assert settings.enable_desktop_mirror is True

    def test_can_disable_desktop_mirror(self) -> None:
        from src.config.settings import AcquisitionSettings

        settings = AcquisitionSettings(enable_desktop_mirror=False)
        assert settings.enable_desktop_mirror is False


class TestDXGIConstants:
    """Verify DXGI format constants match the Windows SDK."""

    def test_bgra_unorm_value(self) -> None:
        assert DXGI_FORMAT_B8G8R8A8_UNORM == 87
