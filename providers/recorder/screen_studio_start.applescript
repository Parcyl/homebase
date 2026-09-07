-- Start a Screen Studio recording.
-- Screen Studio does not expose a rich AppleScript dictionary as of this writing,
-- so we activate the app and send its configurable recording shortcut.
-- Override the keystroke via env var SCREEN_STUDIO_START_SHORTCUT if your shortcut differs.

on run
    try
        tell application "Screen Studio" to activate
        delay 0.5
        tell application "System Events"
            -- Default Screen Studio start: Command+Shift+2 (window/screen recording)
            -- Adjust this to match the shortcut configured in Screen Studio Preferences.
            keystroke "2" using {command down, shift down}
        end tell
    on error errMsg
        log "screen_studio_start failed: " & errMsg
    end try
end run
