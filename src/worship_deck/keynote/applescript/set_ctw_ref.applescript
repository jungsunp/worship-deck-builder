on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set refText to item 3 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        set s to slide slideIndex of d
        -- The 예배의 부름 ref-display slide is ONE box of two paragraphs: a static "예배의 부름"
        -- heading and the bracketed passage citation. Find that box by its heading and overwrite
        -- paragraph 2 with this week's reference (setting paragraph text preserves each
        -- paragraph's style). Off-canvas {0,0} leftovers are skipped.
        repeat with i from 1 to (count of text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set np to count paragraphs of object text of t
                if np ≥ 2 and ((paragraph 1 of object text of t) as text) contains "예배의 부름" then
                    set paragraph 2 of object text of t to refText
                end if
            end if
        end repeat
        save d
        close d saving no
    end tell
    return "ok"
end run
