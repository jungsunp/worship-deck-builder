on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set titleText to item 3 of argv
    set refText to item 4 of argv
    set fontText to item 5 of argv  -- title font (pt) sized to fit the box; "0" = leave unchanged
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- The 말씀 title slide carries two on-canvas text items: a white sermon-title box and a
        -- gold scripture-reference box. Off-canvas items (position {0,0}) are leftover junk and
        -- are skipped. The reference box is the one that reads as a ref ("[눅 22:14-24]" in the template, "눅 22:14-24" once built); classify by
        -- content, never by index, since the order varies. Setting whole object text preserves
        -- each box's base font/color and turns \n into paragraphs.
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if my isRef(txt) then
                    set object text of (text item i of s) to refText
                else
                    -- titleText carries \n line breaks (wrapped to fit); set as paragraphs, then
                    -- shrink the box's font to the fitted size so the title clears the box edges.
                    set object text of (text item i of s) to titleText
                    if fontText is not "0" then
                        set size of object text of (text item i of s) to (fontText as number)
                    end if
                end if
            end if
        end repeat
    end tell
    return "ok"
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
