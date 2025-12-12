# Troubleshooting Guide / Failed Experiences

This document records issues encountered during operation and their solutions to prevent recurrence.

## 1. Task Scheduler: Task Fails with "Operator Refused Request" (0x800710E0)

### Symptom
- The scheduled task fails to start.
- **Error Code**: `2147946720` (Hex: `0x800710E0` - SCHED_E_TASK_ATTEMPTED)
- **Status Message**: "The operator or administrator has refused the request."

### Cause
This error is misleading. It usually means **the task is already running** and the "Multiple Instances Policy" is set to "Do not start a new instance" (IgnoreNew).
It is **not** a permission error in this specific context.

### Solution
- Check if the process (e.g., `aw-qt.exe`) is already running.
- If it is running, no action is needed (working as designed).
- To force a restart, manually kill the existing process first.

---

## 2. PowerShell: Script Crashes on Docker Warnings

### Symptom
- `DigitalTwinNightlyBatch` fails with exit code `1`.
- **Log**: `TerminatingError(docker.exe): "WARNING: Plugin ... is not valid ..."`

### Cause
- The script used `$ErrorActionPreference = "Stop"` for safety.
- PowerShell (incorrectly) interprets standard error (stderr) output from native commands (like `docker info`) as a fatal error if they emit any text to stderr, even if it's just a warning.
- Docker CLI often emits plugin warnings to stderr.

### Solution
- **Do not** run noisy native commands directly in a `try...catch` block with `Stop` preference.
- **Fix**: Use `cmd /c "command > NUL 2>&1"` to isolate the command execution from PowerShell's strict error stream handling.
  ```powershell
  # Bad
  docker info > $null 2>&1

  # Good (Safe)
  cmd /c "docker info > NUL 2>&1"
  ```

---

## 3. Task Scheduler: Missed Schedule (Wake from Sleep Failed)

### Symptom
- The task does not run at the scheduled time (e.g., 2:00 AM) if the PC is asleep.
- The task history shows no attempt to start at that time.

### Causes
1.  **Windows Power Plan**: The default "Balanced" plan often has "Allow wake timers" **Disabled** or set to "Important Wake Timers Only".
2.  **Task Permissions**: Waking the machine requires privileges that `LeastPrivilege` (standard user) usually lacks.

### Solution
1.  **Enable Wake Timers**:
    - `Control Panel` > `Power Options` > `Change plan settings` > `Change advanced power settings`.
    - **Sleep** > **Allow wake timers** -> **Enable**.
2.  **Elevate Task Privileges**:
    - In Task Scheduler properties, check **"Run with highest privileges"**.
