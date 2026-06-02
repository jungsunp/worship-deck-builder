on run argv
    set keyPath to item 1 of argv
    set dateStr to item 2 of argv
    set titleStr to item 3 of argv
    set refStr to item 4 of argv
    set n to 0
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        repeat with s in (slides of d)
            -- A date slide has an on-canvas text item bearing 년/월. Off-canvas items
            -- (position {0, 0}) are leftover junk and are ignored.
            set isDate to false
            repeat with t in (text items of s)
                set p to position of t
                if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                    set txt to (object text of t) as text
                    if (txt contains "년") and (txt contains "월") then set isDate to true
                end if
            end repeat
            if isDate then
                set n to n + 1
                repeat with t in (text items of s)
                    set p to position of t
                    if (item 1 of p) is not 0 or (item 2 of p) is not 0 then
                        set txt to (object text of t) as text
                        if txt contains "[" then
                            -- intro title+ref item: ¶1 = title, ¶2 = ref (brackets included)
                            set paragraph 1 of (object text of t) to titleStr
                            set paragraph 2 of (object text of t) to refStr
                        else if (txt contains "년") and (txt contains "월") then
                            -- date item; ¶1 = date. Any closing line (¶2, ending slides) is kept.
                            set paragraph 1 of (object text of t) to dateStr
                        end if
                    end if
                end repeat
            end if
        end repeat
        save d
        close d saving no
    end tell
    return n
end run
