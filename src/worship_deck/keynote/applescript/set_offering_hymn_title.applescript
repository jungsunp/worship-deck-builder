on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set titleLine to item 3 of argv
    set numberLine to item 4 of argv
    -- The 봉헌 title slide (97) in master.key is ONE on-canvas box of 3 paragraphs — a static
    -- "봉 헌" heading, the bracketed hymn title (e.g. "[ 피난처 있으니 ]"), then the hymn number
    -- (e.g. "(찬 70장)"). Keep the heading and take the title in paragraph 2 / number in paragraph
    -- 3 (setting paragraph text preserves each paragraph's font). Off-canvas {0,0} leftovers are
    -- skipped; the heading box is the multi-paragraph one whose first paragraph is the 봉헌 heading.
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        repeat with i from 1 to (count text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set np to count paragraphs of object text of t
                if np ≥ 3 and ((paragraph 1 of object text of t) as text) contains "봉" then
                    set paragraph 2 of object text of t to titleLine
                    set paragraph 3 of object text of t to numberLine
                end if
            end if
        end repeat
    end tell
    return "ok"
end run
