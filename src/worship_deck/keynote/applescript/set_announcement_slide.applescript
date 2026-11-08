on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set newText to item 3 of argv
    set fontText to item 4 of argv  -- fitted font (pt) from build.py's auto-fit; "0" = leave as is
    -- 교회소식 item slides style the title paragraph gold and the detail paragraphs white in one
    -- vertically centred box (probed from master.key, 16-bit RGB). Setting object text resets all
    -- runs to the box's base font, so we re-apply: size, whole box white, then paragraph 1 gold.
    set goldColor to {65308, 54301, 10093}
    set whiteColor to {65535, 65535, 65535}
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        -- Item slides carry a stacked pair of identical on-canvas text items; off-canvas items
        -- (position {0, 0}) are leftover junk and are skipped. Set + recolor every on-canvas item.
        repeat with t in (text items of s)
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set object text of t to newText
                if fontText is not "0" then
                    set size of object text of t to (fontText as number)
                end if
                set color of object text of t to whiteColor
                if (count paragraphs of object text of t) > 0 then
                    set color of paragraph 1 of object text of t to goldColor
                end if
            end if
        end repeat
    end tell
    return "ok"
end run
