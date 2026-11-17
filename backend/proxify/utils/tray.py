"""
Windows System Tray Adapter — Pure Win32 ctypes implementation.

Provides a lightweight background System Tray icon with context menu and
balloon notifications using native Win32 APIs (`shell32.dll`, `user32.dll`,
`kernel32.dll`) with zero third-party GUI dependencies (no pystray/Pillow
runtime footprint).

Gracefully no-ops on non-Windows platforms.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("proxify.utils.tray")

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    # CRITICAL Win64 type safety: LRESULT is pointer-sized signed integer (64-bit on x64).
    LRESULT = ctypes.c_ssize_t
    UINT_PTR = ctypes.c_size_t
    ULONG_PTR = ctypes.c_size_t
    HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)

    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT),
            ("uCallbackMessage", wintypes.UINT),
            ("hIcon", wintypes.HICON),
            ("szTip", ctypes.c_wchar * 128),
            ("dwState", wintypes.DWORD),
            ("dwStateMask", wintypes.DWORD),
            ("szInfo", ctypes.c_wchar * 256),
            ("uTimeoutOrVersion", wintypes.UINT),
            ("szInfoTitle", ctypes.c_wchar * 64),
            ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", GUID),
            ("hBalloonIcon", wintypes.HICON),
        ]

    # Win32 Constants
    WM_NULL = 0x0000
    WM_DESTROY = 0x0002
    WM_CLOSE = 0x0010
    WM_COMMAND = 0x0111
    WM_USER = 0x0400
    WM_TRAYICON = WM_USER + 20  # 0x0414

    WM_LBUTTONUP = 0x0202
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002

    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_INFO = 0x00000010

    NIIF_INFO = 0x00000001
    NIIF_WARNING = 0x00000002
    NIIF_ERROR = 0x00000003

    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    IDI_APPLICATION = 32512

    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    MF_BYCOMMAND = 0x00000000
    TPM_RIGHTBUTTON = 0x0002
    TPM_NONOTIFY = 0x0080
    TPM_RETURNCMD = 0x0100

    GMEM_MOVEABLE = 0x0002
    CF_UNICODETEXT = 13

    # Menu command IDs
    CMD_OPEN_DASHBOARD = 1001
    CMD_COPY_PROXY = 1002
    CMD_OPEN_LOG = 1003
    CMD_INSTALL_CA = 1004
    CMD_QUIT = 1005

    # Bind DLLs with explicit Win64 argtypes/restype (use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p

    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p

    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL

    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p

    _user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    _user32.RegisterClassExW.restype = wintypes.ATOM

    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.UnregisterClassW.restype = wintypes.BOOL

    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND

    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL

    _user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.DefWindowProcW.restype = LRESULT

    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.GetMessageW.restype = ctypes.c_int

    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL

    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = LRESULT

    _user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.PostMessageW.restype = wintypes.BOOL

    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None

    _user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    _user32.RegisterWindowMessageW.restype = wintypes.UINT

    _user32.LoadImageW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.LoadImageW.restype = wintypes.HANDLE

    _user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    _user32.LoadIconW.restype = wintypes.HICON

    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL

    _shell32.ExtractIconW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
    ]
    _shell32.ExtractIconW.restype = wintypes.HICON

    _shell32.Shell_NotifyIconW.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(NOTIFYICONDATAW),
    ]
    _shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wintypes.HMENU

    _user32.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        UINT_PTR,
        wintypes.LPCWSTR,
    ]
    _user32.AppendMenuW.restype = wintypes.BOOL

    _user32.SetMenuDefaultItem.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.SetMenuDefaultItem.restype = wintypes.BOOL

    _user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    _user32.TrackPopupMenu.restype = ctypes.c_int

    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.DestroyMenu.restype = wintypes.BOOL

    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL

    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL

    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL

    _user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p

    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL


def _copy_text_to_clipboard(text: str) -> bool:
    """Copy a Unicode string onto the Windows Clipboard without external tools."""
    if not IS_WINDOWS:
        return False
    data = (text + "\0").encode("utf-16-le")
    if not _user32.OpenClipboard(None):
        return False
    h_mem = None
    try:
        _user32.EmptyClipboard()
        h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h_mem:
            return False
        ptr = _kernel32.GlobalLock(h_mem)
        if not ptr:
            _kernel32.GlobalFree(h_mem)
            return False
        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            _kernel32.GlobalUnlock(h_mem)
        if not _user32.SetClipboardData(CF_UNICODETEXT, h_mem):
            _kernel32.GlobalFree(h_mem)
            return False
        # Clipboard now owns h_mem on success
        h_mem = None
        return True
    finally:
        _user32.CloseClipboard()


class WindowsSystemTray:
    """Windows System Tray controller running on an isolated Win32 message-pump thread."""

    def __init__(
        self,
        proxy_port: int = 8080,
        dashboard_port: int = 8888,
        log_path: Optional[Path] = None,
        on_quit: Optional[Callable[[], None]] = None,
        on_install_ca: Optional[Callable[[], bool]] = None,
        icon_path: Optional[Path] = None,
        show_startup_toast: bool = True,
    ) -> None:
        self.proxy_port = proxy_port
        self.dashboard_port = dashboard_port
        self.log_path = Path(log_path) if log_path else None
        self.on_quit = on_quit
        self.on_install_ca = on_install_ca
        self.icon_path = Path(icon_path) if icon_path else None
        self.show_startup_toast = show_startup_toast

        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd = None
        self._hicon = None
        self._owns_hicon = False
        self._hinst = None
        self._class_name = f"ProxifyTrayWindow_{os.getpid()}_{id(self)}"
        self._wndproc_ref = None
        self._msg_taskbar_created = 0
        self._icon_added = False
        self._nid_lock = threading.Lock()

    def start(self, wait_timeout: float = 3.0) -> None:
        """Start the tray message-pump thread (non-blocking after tray registers)."""
        if not IS_WINDOWS:
            logger.debug("WindowsSystemTray skipped on non-Windows platform.")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_requested.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="ProxifyTray",
            daemon=True,
        )
        self._thread.start()
        self._ready_event.wait(timeout=wait_timeout)

    def stop(self) -> None:
        """Remove the tray icon and stop the Win32 message loop cleanly."""
        if not IS_WINDOWS:
            return
        self._stop_requested.set()
        self._remove_icon()
        hwnd = self._hwnd
        if hwnd:
            try:
                _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)

    def show_notification(
        self,
        title: str,
        message: str,
        info_flags: int = 1,
    ) -> bool:
        """Display a Windows tray balloon notification."""
        if not IS_WINDOWS:
            return False
        with self._nid_lock:
            if not self._hwnd or not self._icon_added:
                return False
            nid = self._make_nid(flags=NIF_INFO)
            nid.szInfoTitle = title[:63]
            nid.szInfo = message[:255]
            nid.dwInfoFlags = info_flags
            return bool(_shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))

    def _find_icon_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        if self.icon_path:
            candidates.append(self.icon_path)
        pkg_dir = Path(__file__).resolve().parent.parent  # .../proxify
        candidates.append(pkg_dir / "logo.ico")
        try:
            candidates.append(pkg_dir.parent.parent / "assets" / "logo.ico")
        except Exception:
            pass
        try:
            from proxify.utils.compat import get_application_base_dir
            candidates.append(get_application_base_dir() / "logo.ico")
        except Exception:
            pass
        return candidates

    def _load_icon(self):
        """Load tray icon from bundled logo.ico, exe resource, or default app icon."""
        for p in self._find_icon_candidates():
            try:
                if p.is_file():
                    hicon = _user32.LoadImageW(
                        None,
                        str(p),
                        IMAGE_ICON,
                        0,
                        0,
                        LR_LOADFROMFILE | LR_DEFAULTSIZE,
                    )
                    if hicon:
                        self._owns_hicon = True
                        return hicon
            except Exception as e:
                logger.debug("Failed loading icon %s: %s", p, e)

        try:
            exe_icon = _shell32.ExtractIconW(self._hinst, sys.executable, 0)
            # ExtractIconW returns > 1 (or non-NULL handle, 1 means no icon)
            if exe_icon and int(exe_icon) > 1:
                self._owns_hicon = True
                return exe_icon
        except Exception:
            pass

        self._owns_hicon = False
        return _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _make_nid(self, flags: int) -> "NOTIFYICONDATAW":
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        tip = f"Proxify v2.0 — Proxy :{self.proxy_port} | UI :{self.dashboard_port}"
        nid.szTip = tip[:127]
        return nid

    def _add_icon(self) -> bool:
        with self._nid_lock:
            if not self._hwnd:
                return False
            nid = self._make_nid(flags=NIF_MESSAGE | NIF_ICON | NIF_TIP)
            ok = bool(_shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
            self._icon_added = ok
            return ok

    def _remove_icon(self) -> None:
        with self._nid_lock:
            if not self._hwnd or not self._icon_added:
                return
            try:
                nid = self._make_nid(flags=0)
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            except Exception:
                pass
            self._icon_added = False

    def _open_dashboard(self) -> None:
        url = f"http://localhost:{self.dashboard_port}"
        try:
            os.startfile(url)
        except Exception as e:
            logger.error("Cannot open Dashboard URL %s: %s", url, e)

    def _open_log_file(self) -> None:
        if not self.log_path:
            return
        try:
            if not self.log_path.exists():
                self.log_path.touch(exist_ok=True)
            os.startfile(str(self.log_path))
        except Exception as e:
            logger.error("Cannot open log file %s: %s", self.log_path, e)

    def _handle_install_ca(self) -> None:
        def _worker():
            ok = False
            try:
                if self.on_install_ca:
                    ok = bool(self.on_install_ca())
            except Exception as e:
                logger.error("Install CA failed: %s", e)
            if ok:
                self.show_notification(
                    "Proxify — Cài chứng chỉ thành công",
                    "Đã thêm Mitmproxy Root CA vào Windows Root Store.",
                    info_flags=NIIF_INFO,
                )
            else:
                self.show_notification(
                    "Proxify — Cài chứng chỉ thất bại",
                    "Không thể cài tự động Root CA. Kiểm tra proxify.log để xem chi tiết.",
                    info_flags=NIIF_ERROR,
                )

        threading.Thread(target=_worker, name="ProxifyInstallCA", daemon=True).start()

    def _show_context_menu(self, hwnd) -> None:
        hmenu = _user32.CreatePopupMenu()
        if not hmenu:
            return
        try:
            _user32.AppendMenuW(
                hmenu,
                MF_STRING,
                CMD_OPEN_DASHBOARD,
                f"Mở Dashboard (localhost:{self.dashboard_port})",
            )
            _user32.AppendMenuW(
                hmenu,
                MF_STRING,
                CMD_COPY_PROXY,
                f"Sao chép Proxy (127.0.0.1:{self.proxy_port})",
            )
            _user32.AppendMenuW(
                hmenu,
                MF_STRING,
                CMD_OPEN_LOG,
                "Xem file Log (proxify.log)",
            )
            _user32.AppendMenuW(
                hmenu,
                MF_STRING,
                CMD_INSTALL_CA,
                "Cài đặt chứng chỉ HTTPS (Root CA)",
            )
            _user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            _user32.AppendMenuW(hmenu, MF_STRING, CMD_QUIT, "Thoát Proxify")
            _user32.SetMenuDefaultItem(hmenu, CMD_OPEN_DASHBOARD, 0)

            pt = wintypes.POINT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _user32.SetForegroundWindow(hwnd)
            cmd = _user32.TrackPopupMenu(
                hmenu,
                TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                pt.x,
                pt.y,
                0,
                hwnd,
                None,
            )
            _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            _user32.DestroyMenu(hmenu)

        if cmd == CMD_OPEN_DASHBOARD:
            self._open_dashboard()
        elif cmd == CMD_COPY_PROXY:
            addr = f"127.0.0.1:{self.proxy_port}"
            if _copy_text_to_clipboard(addr):
                self.show_notification(
                    "Proxify",
                    f"Đã sao chép địa chỉ Proxy: {addr}",
                    info_flags=NIIF_INFO,
                )
        elif cmd == CMD_OPEN_LOG:
            self._open_log_file()
        elif cmd == CMD_INSTALL_CA:
            self._handle_install_ca()
        elif cmd == CMD_QUIT:
            self._remove_icon()
            if self.on_quit:
                try:
                    self.on_quit()
                except Exception as e:
                    logger.error("Error in tray on_quit callback: %s", e)
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            event = int(lparam) & 0xFFFF
            if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._open_dashboard()
                return 0
            if event == WM_RBUTTONUP:
                self._show_context_menu(hwnd)
                return 0
        elif msg == WM_COMMAND and (int(wparam) & 0xFFFF) == CMD_QUIT:
            self._remove_icon()
            if self.on_quit:
                try:
                    self.on_quit()
                except Exception:
                    pass
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return 0
        elif self._msg_taskbar_created and msg == self._msg_taskbar_created:
            self._add_icon()
            return 0
        elif msg == WM_CLOSE:
            self._remove_icon()
            _user32.DestroyWindow(hwnd)
            return 0
        elif msg == WM_DESTROY:
            self._remove_icon()
            _user32.PostQuitMessage(0)
            return 0

        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run_loop(self) -> None:
        try:
            self._hinst = _kernel32.GetModuleHandleW(None)
            self._hicon = self._load_icon()
            self._msg_taskbar_created = _user32.RegisterWindowMessageW("TaskbarCreated")

            # Keep strong reference to WNDPROC to prevent garbage collection
            self._wndproc_ref = WNDPROC(self._wnd_proc)

            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = self._wndproc_ref
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = self._hinst
            wc.hIcon = self._hicon
            wc.hCursor = None
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = self._class_name
            wc.hIconSm = self._hicon

            atom = _user32.RegisterClassExW(ctypes.byref(wc))
            if not atom:
                err = ctypes.get_last_error()
                logger.warning("RegisterClassExW failed (err=%s); tray disabled.", err)
                return

            self._hwnd = _user32.CreateWindowExW(
                0,
                self._class_name,
                "Proxify Tray Hidden Window",
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                self._hinst,
                None,
            )
            if not self._hwnd:
                err = ctypes.get_last_error()
                logger.warning("CreateWindowExW failed (err=%s); tray disabled.", err)
                return

            if self._add_icon():
                logger.info("📌 Windows System Tray icon active (Proxy :%d | UI :%d).", self.proxy_port, self.dashboard_port)
                if self.show_startup_toast:
                    self.show_notification(
                        "Proxify đang chạy ngầm",
                        f"Proxy: 127.0.0.1:{self.proxy_port} | Giao diện: http://localhost:{self.dashboard_port}",
                        info_flags=NIIF_INFO,
                    )
            else:
                logger.warning("Shell_NotifyIconW(NIM_ADD) failed (err=%s).", ctypes.get_last_error())
        except Exception as e:
            logger.warning("WindowsSystemTray initialization error: %s", e)
        finally:
            self._ready_event.set()

        if not self._hwnd or self._stop_requested.is_set():
            self._cleanup_window()
            return

        msg = wintypes.MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        self._cleanup_window()

    def _cleanup_window(self) -> None:
        self._remove_icon()
        if self._hwnd:
            self._hwnd = None
        try:
            _user32.UnregisterClassW(self._class_name, self._hinst)
        except Exception:
            pass
        if self._hicon and self._owns_hicon:
            try:
                _user32.DestroyIcon(self._hicon)
            except Exception:
                pass
            self._hicon = None
