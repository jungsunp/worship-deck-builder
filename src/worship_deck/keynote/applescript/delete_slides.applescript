on run argv
    set keyPath to item 1 of argv
    set startIdx to (item 2 of argv) as integer
    set cnt to (item 3 of argv) as integer
    tell application "Keynote"
        set d to front document
        -- Deleting slide startIdx cnt times removes cnt consecutive slides: each delete shifts
        -- the next slide down into startIdx.
        repeat cnt times
            delete slide startIdx of d
        end repeat
        set n to count of slides of d
    end tell
    return n
end run
