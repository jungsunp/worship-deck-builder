on run argv
    set templatePath to item 1 of argv
    set outPath to item 2 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set thisDoc to open (POSIX file templatePath)
        save thisDoc in (POSIX file outPath)
        close thisDoc saving no
    end tell
    return outPath
end run
