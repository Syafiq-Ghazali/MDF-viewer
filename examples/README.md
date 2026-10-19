# Example recordings

These are synthetic MDF4 (`.mf4`, MDF version 4.10) files generated for this
project. They contain no hardware captures or private data and can be freely
used to explore the viewer. Open them using **Open MDF…** or pass a path on the
command line.

| File | Contents | Try this |
| --- | --- | --- |
| [motor_drive.mf4](motor_drive.mf4) | Five seconds of bus voltage/reference and three phase currents at 1 kHz; duty cycle at 100 Hz | Put the two bus signals in one panel, currents in another, and duty cycle in a third. Zoom around 2.5 s to inspect a load transient. |
| [edge_cases.mf4](edge_cases.mf4) | Duplicate `Temperature` names in different groups and units, irregular timestamps, NaN, four MDF-invalidated sensor samples, an empty channel, and a text channel | Add both temperatures; identities and units distinguish them. Hover near 0.11 s for the missing temperature or 1.2–1.5 s for invalid voltage. The text channel produces an explanatory warning. |
| [empty_recording.mf4](empty_recording.mf4) | A valid recording with no measurement channels | Verify the browser and panels clear cleanly when switching files. |

To regenerate all three files from the project root after installing dependencies:

```powershell
.\.venv\Scripts\python.exe tools\generate_examples.py
```

To generate a separate copy:

```powershell
.\.venv\Scripts\python.exe tools\generate_examples.py --output C:\Temp\mdf-examples
```

Only the generator contains example-specific channel names; the application
discovers names and identities from each recording.
