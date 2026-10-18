import os
import sys
import subprocess
import winreg

PROXY_SERVER = "http://127.0.0.1:8080"
PROXY_HOST_PORT = "127.0.0.1:8080"
PROXY_BYPASS_LIST = (
    "localhost;127.0.0.1;<local>;192.168.*;10.*;172.16.*;"
    "accounts.google.com;accounts.youtube.com"
)
POLICY_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Google\Chrome", "HKLM"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Policies\Google\Chrome", "HKCU"),
]


def get_chrome_registry_status() -> bool:
    """Return True if Chrome proxy policy is currently active in HKCU or HKLM."""
    for root_hive, subkey, _ in POLICY_PATHS:
        try:
            key = winreg.OpenKey(root_hive, subkey, 0, winreg.KEY_READ)
            mode, _ = winreg.QueryValueEx(key, "ProxyMode")
            winreg.CloseKey(key)
            if mode == "fixed_servers":
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


def apply_chrome_registry_policy():
    """Apply Chrome-native proxy policy in Windows Registry (zero impact on Windows System Proxy)."""
    for root_hive, subkey, hive_name in POLICY_PATHS:
        try:
            key = winreg.CreateKeyEx(root_hive, subkey, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, "ProxyMode", 0, winreg.REG_SZ, "fixed_servers")
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, PROXY_HOST_PORT)
            winreg.SetValueEx(key, "ProxyBypassList", 0, winreg.REG_SZ, PROXY_BYPASS_LIST)
            winreg.CloseKey(key)
            print(f"[OK] Enabled Chrome native proxy policy in {hive_name}\\{subkey}")
        except Exception as e:
            print(f"[WARN] Could not set registry policy in {hive_name}\\{subkey}: {e}")


def remove_chrome_registry_policy():
    """Remove Chrome proxy policy from Windows Registry to restore original Chrome behavior."""
    value_names = ("ProxyMode", "ProxyServer", "ProxyBypassList")
    for root_hive, subkey, hive_name in POLICY_PATHS:
        try:
            key = winreg.OpenKey(root_hive, subkey, 0, winreg.KEY_SET_VALUE)
            removed = []
            for val_name in value_names:
                try:
                    winreg.DeleteValue(key, val_name)
                    removed.append(val_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            if removed:
                print(f"[OK] Removed {removed} from {hive_name}\\{subkey}")
            else:
                print(f"[OK] {hive_name}\\{subkey} is already clean")
        except FileNotFoundError:
            print(f"[OK] {hive_name}\\{subkey} does not exist (already clean)")
        except Exception as e:
            print(f"[WARN] Could not clean registry policy in {hive_name}\\{subkey}: {e}")


def update_all_chrome_shortcuts(enable_proxy_flags: bool = False):
    """Add or strip --proxy-server and --proxy-bypass-list across all Chrome shortcuts."""
    mode_flag = "$true" if enable_proxy_flags else "$false"
    ps_script = f'''
$enableProxy = {mode_flag}
$proxyServer = '{PROXY_SERVER}'
$bypassList = '{PROXY_BYPASS_LIST}'
$proxyArgs = '--proxy-server="' + $proxyServer + '" --proxy-bypass-list="' + $bypassList + '"'

$searchDirs = @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory"),
    "$env:APPDATA\\Microsoft\\Internet Explorer\\Quick Launch\\User Pinned\\TaskBar",
    "$env:APPDATA\\Microsoft\\Internet Explorer\\Quick Launch\\User Pinned\\ImplicitAppShortcuts",
    "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs",
    "$env:PROGRAMDATA\\Microsoft\\Windows\\Start Menu\\Programs"
)

$sh = New-Object -ComObject WScript.Shell
foreach ($dir in $searchDirs) {{
    if (Test-Path $dir) {{
        Get-ChildItem -Path $dir -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {{
            try {{
                $sc = $sh.CreateShortcut($_.FullName)
                if ($sc.TargetPath -like "*chrome.exe*") {{
                    $existing = $sc.Arguments
                    # Preserve --profile-directory if present, strip old --proxy-server and --proxy-bypass-list
                    $cleaned = ($existing -replace '--proxy-server="[^"]*"', '' -replace '--proxy-bypass-list="[^"]*"', '').Trim()
                    if ($enableProxy) {{
                        if ($cleaned) {{
                            $sc.Arguments = "$cleaned $proxyArgs"
                        }} else {{
                            $sc.Arguments = $proxyArgs
                        }}
                        $sc.Save()
                        Write-Host "[OK] Injected proxy flags into shortcut:" $_.FullName "->" $sc.Arguments
                    }} else {{
                        if ($existing -ne $cleaned) {{
                            $sc.Arguments = $cleaned
                            $sc.Save()
                            Write-Host "[OK] Restored original shortcut:" $_.FullName "->" $sc.Arguments
                        }}
                    }}
                }}
            }} catch {{
                Write-Host "[WARN] Failed to update shortcut:" $_.FullName $_
            }}
        }}
    }}
}}
'''
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
    if res.stdout.strip():
        print(res.stdout.strip())
    if res.stderr.strip():
        print("Stderr:", res.stderr.strip())


def restart_chrome_cleanly():
    """Restart Chrome cleanly without --proxy-server flags while restoring all open tabs."""
    import time
    print("[INFO] Closing old Chrome processes with --proxy-server flags...")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", 'Stop-Process -Name "chrome" -Force -ErrorAction SilentlyContinue'],
        capture_output=True,
        text=True,
    )
    time.sleep(1.5)
    chrome_exe = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_exe):
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            [chrome_exe, "--restore-last-session"],
            creationflags=DETACHED_PROCESS,
            close_fds=True,
        )
        print("[OK] Relaunched Chrome cleanly (without proxy flags) and restored tabs!")


def disable_chrome_proxy(restart_chrome: bool = False):
    """Restore Chrome to 100% original state (clean Registry Policy + clean Shortcuts)."""
    print("=== Restoring Chrome to Original (Direct / Native) Mode ===")
    remove_chrome_registry_policy()
    update_all_chrome_shortcuts(enable_proxy_flags=False)
    if restart_chrome:
        restart_chrome_cleanly()
    print("[DONE] Chrome is now restored to original mode (Proxify proxy disabled).")


def enable_chrome_proxy(with_shortcuts: bool = False):
    """Enable Proxify proxy for Chrome via Registry Policy (and optionally shortcut flags)."""
    print("=== Enabling Proxify Proxy for Chrome ===")
    apply_chrome_registry_policy()
    update_all_chrome_shortcuts(enable_proxy_flags=with_shortcuts)
    print("[DONE] Chrome is now routed through Proxify (127.0.0.1:8080).")


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "toggle"
    with_shortcuts = "--with-shortcuts" in sys.argv
    restart_flag = "--restart" in sys.argv or cmd == "restart"

    if cmd in ("disable", "off", "restore", "clean", "restart"):
        disable_chrome_proxy(restart_chrome=restart_flag)
    elif cmd in ("enable", "on"):
        enable_chrome_proxy(with_shortcuts=with_shortcuts)
    elif cmd == "status":
        is_on = get_chrome_registry_status()
        print(f"Chrome Registry Proxy Policy: {'ACTIVE (127.0.0.1:8080)' if is_on else 'OFF (Original / Extension-controlled)'}")
    else:
        # Toggle mode
        if get_chrome_registry_status():
            disable_chrome_proxy(restart_chrome=restart_flag)
        else:
            enable_chrome_proxy(with_shortcuts=with_shortcuts)

