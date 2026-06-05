on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set newText to item 3 of argv
    -- 교회소식 item slides style the title paragraph gold and the detail paragraphs white in one
    -- top-anchored box (probed from master.key, 16-bit RGB). Setting object text resets all runs
    -- to the box's base font, so we re-apply: whole box white, then paragraph 1 (title) gold.
    set goldColor to {65308, 54301, 10093}
    set whiteColor to {65535, 65535, 65535}
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        set s to slide slideIndex of d
        -- Item slides carry a stacked pair of identical on-canvas text items; off-canvas items
        -- (position {0, 0}) are leftover junk and are skipped. Set + recolor every on-canvas item.
        repeat with t in (text items of s)
            set p to position of t
            if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                set object text of t to newText
                set color of object text of t to whiteColor
                if (count paragraphs of object text of t) > 0 then
                    set color of paragraph 1 of object text of t to goldColor
                end if
            end if
        end repeat
        save d
        close d saving no
    end tell
    return "ok"
end run
