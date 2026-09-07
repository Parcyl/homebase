-- Toggle Vowen capture via its Hands-Free Mode shortcut.
-- Configure Vowen -> Settings -> Shortcuts -> Hands-Free Mode as Control + Shift
-- (modifier-only; no letter key). AppleScript fires both modifiers down then up.
--
-- If you change Vowen's shortcut in Preferences, update both vowen_start.applescript
-- and vowen_stop.applescript to match. The two files are intentionally identical
-- because Vowen's Hands-Free Mode is a single toggle (tap to start, tap to stop).

on run
    try
        tell application "Vowen" to activate
        delay 0.4
        tell application "System Events"
            key down control
            key down shift
            delay 0.08
            key up shift
            key up control
        end tell
    on error errMsg
        log "vowen_start failed: " & errMsg
    end try
end run
