on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set titleLine to item 3 of argv
    -- The 고백의 찬양 divider slide (57) in master.key is ONE on-canvas box of 2 paragraphs — a
    -- static "고백의 찬양" heading, then the bracketed song title (e.g. "[ 주만 바라 볼찌라 ]").
    -- Keep the heading and take the title in paragraph 2 (setting paragraph text preserves the
    -- paragraph's font). Off-canvas {0,0} leftovers are skipped; the heading box is the
    -- multi-paragraph one whose first paragraph is the 고백 heading.
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        repeat with i from 1 to (count text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set np to count paragraphs of object text of t
                if np ≥ 2 and ((paragraph 1 of object text of t) as text) contains "고백" then
                    set paragraph 2 of object text of t to titleLine
                end if
            end if
        end repeat
    end tell
    return "ok"
end run
