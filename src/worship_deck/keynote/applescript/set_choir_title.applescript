on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set titleText to item 3 of argv
    set composerText to item 4 of argv
    -- The two 성가대 title slides in master.key are laid out differently:
    --   * the section-divider slide (77) is ONE box of 3 paragraphs — a static "성가대 찬양"
    --     heading, the song title, then the composer credit (each paragraph keeps its own font);
    --   * the title-card slide (78) is a single-line lower-third bar showing "title composer".
    -- So branch per on-canvas box: a multi-paragraph box whose first paragraph is the 성가대
    -- heading keeps that heading and takes the title in paragraph 2 / composer in paragraph 3
    -- (setting paragraph text preserves each paragraph's style); any other box is the one-line
    -- bar and takes the combined "title composer" line. Off-canvas {0,0} leftovers are skipped.
    if composerText is not "" then
        set lineText to titleText & " " & composerText
    else
        set lineText to titleText
    end if
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        repeat with i from 1 to (count text items of s)
            set t to text item i of s
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set np to count paragraphs of object text of t
                if np ≥ 2 and ((paragraph 1 of object text of t) as text) contains "성가대" then
                    set paragraph 2 of object text of t to titleText
                    if np ≥ 3 then set paragraph 3 of object text of t to composerText
                else
                    set object text of t to lineText
                end if
            end if
        end repeat
    end tell
    return "ok"
end run
