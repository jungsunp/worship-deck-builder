on run argv
    -- argv: keyPath (logging only — operates on the open front document like every primitive).
    -- Emit every slide's text items under a ###SLIDE n### marker (the deck-text dump
    -- technique from docs/gotchas.md); the Python wrapper dedupes the stacked/off-canvas
    -- duplicate boxes per slide. Read-only: detects section anchors at build time (#98).
    set out to {}
    tell application "Keynote"
        set d to front document
        repeat with i from 1 to (count of slides of d)
            set end of out to "###SLIDE " & (i as text) & "###"
            set s to slide i of d
            repeat with t in (text items of s)
                set end of out to (object text of t) as text
            end repeat
        end repeat
    end tell
    set {tid, AppleScript's text item delimiters} to {AppleScript's text item delimiters, linefeed}
    set joined to out as text
    set AppleScript's text item delimiters to tid
    return joined
end run
