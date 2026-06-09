on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set newText to item 3 of argv
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- Worship-song title and lyric slides each carry a pair of stacked, identical on-canvas
        -- text items; off-canvas items (position {0, 0}) are leftover junk and are skipped. Set
        -- every on-canvas item so the visible text stays consistent. Setting whole object text
        -- preserves the box's base font and turns \n into paragraphs.
        repeat with t in (text items of s)
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set object text of t to newText
            end if
        end repeat
    end tell
    return "ok"
end run
