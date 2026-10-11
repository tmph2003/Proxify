import os
import subprocess

vbs_content = r'''
Dim oShell, oFSO, desktop, taskbar, sc1, sc2
Set oShell = CreateObject("WScript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")

desktop = oShell.SpecialFolders("Desktop")
Set sc1 = oShell.CreateShortcut(desktop & "\Google Chrome (Proxify).lnk")
sc1.TargetPath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
sc1.Arguments = "--proxy-server=""http://127.0.0.1:8080"" --proxy-bypass-list=""localhost;127.0.0.1;<local>;192.168.*;10.*;172.16.*;*.sunhouse.com.vn;14.232.214.249;*.zadn.vn;*.zing.vn;mail.google.com;chat.google.com;accounts.google.com;accounts.youtube.com"""
sc1.IconLocation = "C:\Program Files\Google\Chrome\Application\chrome.exe,0"
sc1.Save

taskbar = oShell.ExpandEnvironmentStrings("%APPDATA%\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Google Chrome.lnk")
If oFSO.FileExists(taskbar) Then
    Set sc2 = oShell.CreateShortcut(taskbar)
    sc2.TargetPath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
    sc2.Arguments = sc1.Arguments
    sc2.IconLocation = sc1.IconLocation
    sc2.Save
End If
'''

vbs_path = os.path.join(os.path.dirname(__file__), 'create_shortcut.vbs')
with open(vbs_path, 'w', encoding='utf-8') as f:
    f.write(vbs_content)

res = subprocess.run(['cscript', '//nologo', vbs_path], capture_output=True, text=True)
print('Result code:', res.returncode)
print('Stdout:', res.stdout)
print('Stderr:', res.stderr)

if os.path.exists(vbs_path):
    os.remove(vbs_path)
