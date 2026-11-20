on run argv
    set keyPath to item 1 of argv
    set dateStr to item 2 of argv
    set titleStr to item 3 of argv
    set refStr to item 4 of argv
    set n to 0
    tell application "Keynote"
        set d to front document
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
                        if (txt contains "[") or my isIntro(t) then
                            -- intro title+ref item: ¶1 = title, ¶2 = ref (bare, or bracketed in the template)
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
    end tell
    return n
end run

-- True for a scripture-ref text: bracketed ("[눅 22:14-24]", the template) or bare ("눅 22:14-24",
-- what builds write). Bare = a digit on both sides of a ":".
on isRef(txt)
    if txt contains "[" then return true
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to ":"
    set parts to text items of txt
    set AppleScript's text item delimiters to oldDelims
    if (count of parts) < 2 then return false
    set a to (item 1 of parts) as text
    set b to (item 2 of parts) as text
    if (length of a) < 1 or (length of b) < 1 then return false
    return ((last character of a) is in "0123456789") and ((first character of b) is in "0123456789")
end isRef

-- Bare-form intro item: title + ref paragraphs, ¶2 reads as a ref and ¶1 is not a date.
on isIntro(t)
    tell application "Keynote"
        if (count paragraphs of (object text of t)) < 2 then return false
        set p1 to (paragraph 1 of (object text of t)) as text
        set p2 to (paragraph 2 of (object text of t)) as text
    end tell
    return (my isRef(p2)) and not ((p1 contains "년") and (p1 contains "월"))
end isIntro
