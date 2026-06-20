on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set noteText to item 3 of argv
    tell application "Keynote"
        set d to front document
        -- Presenter notes show only on the operator's presenter display, never on the projected
        -- slide, so a section label (V1/C/Tag…) here lets the operator navigate without the
        -- audience seeing it (#113).
        set presenter notes of slide slideIndex of d to noteText
    end tell
    return "ok"
end run
