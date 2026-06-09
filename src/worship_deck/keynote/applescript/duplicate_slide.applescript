on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set dupCount to (item 3 of argv) as integer
    tell application "Keynote"
        set thisDoc to front document
        tell thisDoc
            -- Keynote appends a bare `duplicate` to the end, so place each copy
            -- explicitly after the previous one to keep the block contiguous.
            repeat with k from 1 to dupCount
                duplicate slide slideIndex to after slide (slideIndex + k - 1)
            end repeat
            set n to count of slides
        end tell
    end tell
    return n
end run
