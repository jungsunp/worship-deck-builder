on run argv
    set keyPath to item 1 of argv
    set srcStart to (item 2 of argv) as integer
    set srcLen to (item 3 of argv) as integer
    set destAfter to (item 4 of argv) as integer
    set dupTimes to (item 5 of argv) as integer
    tell application "Keynote"
        set d to front document
        tell d
            -- Copy the contiguous block [srcStart .. srcStart+srcLen-1] to after slide
            -- destAfter, dupTimes times, preserving block order. The source block MUST sit
            -- entirely before destAfter so its indices never shift as copies are inserted
            -- after destAfter; insertAt advances per copied slide to keep order.
            set insertAt to destAfter
            repeat dupTimes times
                repeat with j from 0 to (srcLen - 1)
                    duplicate slide (srcStart + j) to after slide insertAt
                    set insertAt to insertAt + 1
                end repeat
            end repeat
            set n to count of slides
        end tell
    end tell
    return n
end run
