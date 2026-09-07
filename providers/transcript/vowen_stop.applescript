-- Toggle Vowen Hands-Free Mode off (same Control+Shift modifier-only hotkey).
-- See vowen_start.applescript for context.

on run
    try
        tell application "Vowen" to activate
        delay 0.3
        tell application "System Events"
            key down control
            key down shift
            delay 0.08
            key up shift
            key up control
        end tell
    on error errMsg
        log "vowen_stop failed: " & errMsg
    end try
end run
