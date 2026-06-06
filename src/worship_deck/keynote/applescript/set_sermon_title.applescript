on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set titleText to item 3 of argv
    set refText to item 4 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        set s to slide slideIndex of d
        -- The 말씀 title slide carries two on-canvas text items: a white sermon-title box and a
        -- gold scripture-reference box. Off-canvas items (position {0,0}) are leftover junk and
        -- are skipped. The reference box is the bracketed one (e.g. "[눅 22:14-24]"); classify by
        -- content, never by index, since the order varies. Setting whole object text preserves
        -- each box's base font/color and turns \n into paragraphs.
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if txt contains "[" then
                    set object text of (text item i of s) to refText
                else
                    set object text of (text item i of s) to titleText
                end if
            end if
        end repeat
        save d
        close d saving no
    end tell
    return "ok"
end run
