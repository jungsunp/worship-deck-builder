on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- The sermon-title box is the on-canvas (position not {0,0}) text item that is NOT the
        -- scripture-ref box (bracketed or bare). Return its width, height, and base font size so the caller
        -- can wrap/shrink the title to fit. Off-canvas {0,0} leftovers are skipped.
        set out to ""
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if not my isRef(txt) then
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

-- True for a scripture-ref text: bracketed ("[눅 22:14-24]", the template) or bare ("눅 22:14-24",
-- what builds write). Bare = a digit on both sides of a ":".
on isRef(txt)
    if txt contains "[" then return true
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to ":"
    set parts to text items of txt
    set AppleScript's text item delimiters to oldDelims
    if (count of parts) < 2 then return false
    set a to (item 1 of parts) as text
    set b to (item 2 of parts) as text
    if (length of a) < 1 or (length of b) < 1 then return false
    return ((last character of a) is in "0123456789") and ((first character of b) is in "0123456789")
end isRef
