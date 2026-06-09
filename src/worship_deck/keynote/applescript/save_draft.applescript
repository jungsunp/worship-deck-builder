on run argv
    set templatePath to item 1 of argv
    set outPath to item 2 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set thisDoc to open (POSIX file templatePath)
        -- Write a pristine copy to outPath so the draft file exists early (#117). NOTE: `save … in`
        -- does NOT rebind the open document — thisDoc stays bound to the *template*. The build then
        -- mutates this open front document in place, and `finalize.applescript` saves it WITH the
        -- explicit outPath at the end (a bare `save` would write the template). The template file
        -- itself is never saved, so it stays untouched.
        save thisDoc in (POSIX file outPath)
    end tell
    return outPath
end run
