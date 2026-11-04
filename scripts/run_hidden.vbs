' Keep this file ASCII: Windows Script Host does not read UTF-8 comments reliably.
Option Explicit
Dim shell, cmd, i, arg
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count = 0 Then WScript.Quit 2
cmd = ""
For i = 0 To WScript.Arguments.Count - 1
    arg = WScript.Arguments(i)
    If arg = "" Or InStr(arg, " ") > 0 Or InStr(arg, vbTab) > 0 Then arg = """" & arg & """"
    If i > 0 Then cmd = cmd & " "
    cmd = cmd & arg
Next
' Hidden window; keep the task alive and return the actual child exit code.
WScript.Quit shell.Run(cmd, 0, True)
