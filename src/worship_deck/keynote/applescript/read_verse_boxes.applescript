on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- The two verse bodies are the on-canvas (position not {0,0}) text items that are not
        -- the 개역한글/ESV labels. Korean sits above English (smaller y).
        set bodies to {}
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if (txt does not contain "개역한글") and (txt does not contain "ESV") then
                    set end of bodies to (text item i of s)
                end if
            end if
        end repeat
        set b1 to item 1 of bodies
        set b2 to item 2 of bodies
        set p1 to position of b1
        set p2 to position of b2
        if (item 2 of p1) <= (item 2 of p2) then
            set koBody to b1
            set enBody to b2
        else
            set koBody to b2
            set enBody to b1
        end if
        set out to (((width of koBody) as integer) as text) & " " & (((height of koBody) as integer) as text) & linefeed
        set out to out & (((width of enBody) as integer) as text) & " " & (((height of enBody) as integer) as text)
    end tell
    return out
end run
