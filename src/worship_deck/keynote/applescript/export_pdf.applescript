on run argv
    set outPath to item 1 of argv
    -- Export the open draft (front document) to PDF for phone preview (#23). The build leaves
    -- the draft open as `front document` (open-once/save-once, #117), so this exports it in
    -- place — never re-opening the .key (re-opening an open deck returns missing value/-1700).
    -- Keynote's default PDF export emits every slide (stages flattened), which is what we want
    -- for a review preview.
    tell application "Keynote"
        export front document to (POSIX file outPath) as PDF
    end tell
    return outPath
end run
