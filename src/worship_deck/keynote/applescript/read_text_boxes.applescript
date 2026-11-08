on run argv
    set keyPath to item 1 of argv
    set startIndex to (item 2 of argv) as integer
    set slideCount to (item 3 of argv) as integer
    -- For each slide in the range, the first on-canvas text item's width, height, font name and
    -- nominal size, tab-separated, one slide per line — what the 교회소식 and 성가대 title-card
    -- auto-fits measure against (box heights differ per slide). Off-canvas {0,0} leftovers skipped.
    set out to ""
    tell application "Keynote"
        set d to front document
        repeat with k from startIndex to (startIndex + slideCount - 1)
            set s to slide k of d
            repeat with t in (text items of s)
                set p to position of t
                if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                    set out to out & (((width of t) as integer) as text) & tab & ¬
                        (((height of t) as integer) as text) & tab & ¬
                        (font of object text of t) & tab & ¬
                        (((size of object text of t) as integer) as text) & linefeed
                    exit repeat
                end if
            end repeat
        end repeat
    end tell
    return out
end run
