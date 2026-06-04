on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set krLabel to item 3 of argv
    set krText to item 4 of argv
    set enLabel to item 5 of argv
    set enText to item 6 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        set s to slide slideIndex of d
        -- Classify the 4 on-canvas text items. Off-canvas items (position {0,0}) are
        -- leftover junk and are skipped. Items: a 개역한글 label + body, an ESV label + body.
        -- Order differs across slides, so classify by content + y-position, never by index.
        set krLabelItem to missing value
        set enLabelItem to missing value
        set bodies to {}
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set txt to (object text of t) as text
                if txt contains "개역한글" then
                    set krLabelItem to (text item i of s)
                else if txt contains "ESV" then
                    set enLabelItem to (text item i of s)
                else
                    set end of bodies to (text item i of s)
                end if
            end if
        end repeat
        -- Korean body sits above English body (smaller y).
        set b1 to item 1 of bodies
        set b2 to item 2 of bodies
        set p1 to position of b1
        set p2 to position of b2
        if (item 2 of p1) <= (item 2 of p2) then
            set krBody to b1
            set enBody to b2
        else
            set krBody to b2
            set enBody to b1
        end if
        set object text of krLabelItem to krLabel
        set object text of krBody to krText
        set object text of enLabelItem to enLabel
        set object text of enBody to enText
        save d
        close d saving no
    end tell
    return "ok"
end run
