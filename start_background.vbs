Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
botDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = botDir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonw) Then
    MsgBox "The Hangeul bot was not started." & vbCrLf & vbCrLf & _
           pythonw & " is missing." & vbCrLf & _
           "Create the Python 3.12 environment in " & botDir & " first (see the top of requirements.txt).", _
           vbCritical, "Hangeul Bot"
    WScript.Quit 1
End If
WshShell.CurrentDirectory = botDir
WshShell.Run """" & pythonw & """ run.py", 0, False
