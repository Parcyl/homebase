-- Stop the active Screen Studio recording.
-- Uses Screen Studio's stop-recording shortcut. Configure to match the one set in Screen Studio Preferences.

on run
    try
        tell application "Screen Studio" to activate
        delay 0.3
        tell application "System Events"
            -- Screen Studio's default stop shortcut is the same combo used to start;
            -- some setups use Command+Shift+5 or a dedicated stop key. Adjust to your setup.
            keystroke "2" using {command down, shift down}
        end tell
    on error errMsg
        log "screen_studio_stop failed: " & errMsg
    end try
end run
