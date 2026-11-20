on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set krText to item 3 of argv   -- bare Korean ref, e.g. "삼상 5:1-12"
    set enText to item 4 of argv   -- English ref, e.g. "1 Samuel 5:1-12" (bare)
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- The 말씀 scripture-ref recap slide (shown before the sermon reading) carries two on-canvas
        -- text boxes: a Korean reference and an English one (e.g. "Luke 22:14-24"; bracketed in the template).
        -- Classify by content — the box with Latin letters is English — never by index. Setting whole object
        -- text preserves each box's base font/color. Off-canvas {0,0} leftovers are skipped.
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if my hasLatin(txt) then
                    set object text of (text item i of s) to enText
                else
                    set object text of (text item i of s) to krText
                end if
            end if
        end repeat
    end tell
    return "ok"
end run

-- True when the text has an ASCII letter (the English ref; the Korean one has none).
on hasLatin(txt)
    repeat with c in (characters of txt)
        if c is in "abcdefghijklmnopqrstuvwxyz" then return true
    end repeat
    return false
end hasLatin
