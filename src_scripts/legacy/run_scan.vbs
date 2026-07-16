Set objFSO = CreateObject("Scripting.FileSystemObject")
strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python """ & strPath & "\scan_black_swan.py"" --no-popup", 0, False
