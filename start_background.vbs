Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\BOT"
WshShell.Run """C:\Users\User\AppData\Local\Programs\Python\Python311\pythonw.exe"" run.py", 0, False
