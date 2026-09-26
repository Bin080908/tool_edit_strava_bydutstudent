Set WshShell = CreateObject("WScript.Shell")
On Error Resume Next
Set oShortcut1 = WshShell.CreateShortcut(WshShell.SpecialFolders("Desktop") & "\Strava FIT Studio.lnk")
oShortcut1.TargetPath = "C:\Users\Hoangviet\Documents\strava\run_app.bat"
oShortcut1.WorkingDirectory = "C:\Users\Hoangviet\Documents\strava"
oShortcut1.IconLocation = "shell32.dll,245"
oShortcut1.Description = "Strava FIT Studio - Banh Hoang Viet 26ES"
oShortcut1.Save

Set oShortcut2 = WshShell.CreateShortcut("C:\Users\Hoangviet\Desktop\Strava FIT Studio.lnk")
oShortcut2.TargetPath = "C:\Users\Hoangviet\Documents\strava\run_app.bat"
oShortcut2.WorkingDirectory = "C:\Users\Hoangviet\Documents\strava"
oShortcut2.IconLocation = "shell32.dll,245"
oShortcut2.Description = "Strava FIT Studio - Banh Hoang Viet 26ES"
oShortcut2.Save
