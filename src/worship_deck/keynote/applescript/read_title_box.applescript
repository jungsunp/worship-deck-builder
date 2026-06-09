on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- The sermon-title box is the on-canvas (position not {0,0}) text item that is NOT the
        -- bracketed scripture-ref box. Return its width, height, and base font size so the caller
        -- can wrap/shrink the title to fit. Off-canvas {0,0} leftovers are skipped.
        set out to ""
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if txt does not contain "[" then
                    set fs to size of object text of t
                    set out to (((width of t) as integer) as text) & " " & ¬
                        (((height of t) as integer) as text) & " " & (fs as text)
                    exit repeat
                end if
            end if
        end repeat
    end tell
    return out
end run
