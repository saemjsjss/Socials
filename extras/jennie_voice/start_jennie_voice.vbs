' Starts the Jennie voice service (service.py) hidden, from this folder, with this folder's venv.
' Used by the JennieVoice.lnk startup shortcut and by watchdog_jennie_voice.ps1.
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
voiceDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = voiceDir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "The Jennie voice service was not started." & vbCrLf & vbCrLf & _
           pythonw & " is missing." & vbCrLf & _
           "Create the Python 3.12 environment in " & voiceDir & " first (see README.md and the top of requirements.txt).", _
           vbCritical, "Jennie voice"
    WScript.Quit 1
End If
WshShell.CurrentDirectory = voiceDir
WshShell.Run """" & pythonw & """ service.py", 0, False
