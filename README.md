# Self-Healing Process Manager

A Python implementation of the project abstract's monitor → classify → decide → intervene → verify loop. Its CPU protection feature looks for sustained high CPU while desktop input has been idle and the selected process is not the foreground application. It tries a softer action first and escalates only if CPU remains high after the verification window.

## Install and run

Requires Python 3.10 or newer on macOS, Linux, or Windows. From the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python -m process_manager dashboard
```

Open http://127.0.0.1:5050. The dashboard starts a bounded 90-second CPU demonstration. Keep the terminal running. Stop it with Ctrl+C. The database is `data/manager.sqlite3`.

To observe one existing process without allowing changes, specify its PID:

```sh
python -m process_manager watch 12345
```

To authorize automatic control of that one selected PID:

```sh
python -m process_manager watch 12345 --auto-kill
```

This explicit opt-in can throttle or terminate that PID only when the policy verifies sustained critical CPU, sufficient desktop idle time, and that the process is not foreground. To discover processes owned by your current account and enable the same guarded policy for them, use `python -m process_manager watch --all-user-processes --auto-kill`. This mode excludes the manager and its parent process chain, ignores other accounts, and respects protected process names. Review the protected list and idle settings before enabling it. Restart is available only for commands launched by this manager. `--no-enforce` disables process controls. The dashboard binds to loopback only.

To supervise a command started by the manager:

```sh
python -m process_manager run -- python demos/workload.py cpu
```

The demo workloads in `demos/workload.py` are bounded or local and affect only their own process.

## What “not in use” means

The manager does not claim to understand a person's intent. The default rule is deliberately conservative: a process is eligible for CPU termination only when all of these are true:

- It has exceeded the critical CPU threshold for the configured number of consecutive samples.
- The desktop has received no recent input for `unused_user_idle_seconds`.
- The operating system identifies a foreground process, and the monitored PID is not that foreground process.
- The PID was explicitly launched by the manager, selected with `watch PID --auto-kill`, or discovered in the opt-in `watch --all-user-processes --auto-kill` mode.
- Its name is not in the protected process list.

If the platform cannot determine both user idle time and the foreground PID, automatic CPU termination is disabled. A process running in the background may still be doing work the user wants; adjust the policy to fit your environment and keep observation-only mode until you have reviewed behavior.

## Recovery behavior

`config/policy.yaml` controls sample intervals, thresholds, idle time, recovery verification, resource limits, and action order. CPU must stay above the warning threshold for `cpu_sustain_samples` consecutive samples. Warning CPU load can be throttled only after the process is established as background and the desktop is idle. Critical, unused CPU load follows the configured ladder:

1. Lower priority and briefly suspend/resume.
2. For manager-launched processes, restart the command.
3. If CPU remains above `cpu_recovery_percent` after each verification window, terminate it.

The UI and SQLite `actions` table distinguish whether the control was applied (`result`) and whether it actually restored CPU (`outcome`). If the user becomes active or the foreground process changes during verification, escalation stops. An intentional termination removes that process from active monitoring, so it is not mistaken for a crash and restarted again.

Memory thresholds, memory growth, application heartbeat hangs, and managed-process crashes are also classified. Hang detection requires an application to register and send a heartbeat; sleeping alone is not considered a hang. All samples, incidents, decisions, actions, and action outcomes are stored in SQLite.

## Desktop support and limits

- **macOS:** idle time must be confirmed by both Quartz input-event timing and IOHIDSystem; the foreground PID is read through System Events. The dashboard only reports activity as supported when both idle readings and the foreground PID are available. If either idle source is missing or they disagree, automatic termination is disabled. macOS may require allowing Terminal/Python to control System Events in Privacy & Security settings. If the foreground PID cannot be read, the monitor fails safe and does not automatically terminate for CPU.
- **Windows:** last input and foreground PID use Windows APIs.
- **Linux/X11:** install `xprintidle` and `xdotool` and run inside an X11 desktop session. Wayland and headless sessions may not expose the required signals; in that case this implementation refuses CPU auto-termination.
- Priority, signals, Linux `/proc`, and POSIX `RLIMIT_CPU`/`RLIMIT_AS` are platform-specific. Resource limits are optional and off by default. Windows hard resource limits are not implemented.

This is a course project rather than a production supervisor. It acts only on explicitly selected or manager-launched processes, blocks common system process names, and never treats unknown desktop activity as proof of inactivity.

## Tests

```sh
python -m pytest -q
```

Tests cover sustained-severity rules, foreground and idle safety checks, policy configuration, event and outcome persistence, managed launch, explicit external-process authorization, escalation after an ineffective throttle, and the dashboard API.
