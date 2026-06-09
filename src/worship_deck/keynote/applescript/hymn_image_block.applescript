on run argv
    set keyPath to item 1 of argv
    set startIndex to (item 2 of argv) as integer
    set maxScan to (item 3 of argv) as integer
    tell application "Keynote"
        set d to front document
        set total to count of slides of d
        set lastScan to startIndex + maxScan
        if lastScan > total then set lastScan to total
        -- The 봉헌 block is the contiguous run of image-bearing slides starting at/after
        -- startIndex: the section's title/intro slides carry only native text (no image), so the
        -- first image slide marks the start of last week's hymn pages, and the first text-only
        -- slide after them marks the next section.
        set firstImg to 0
        set i to startIndex
        repeat while i ≤ lastScan
            if (count of images of slide i of d) > 0 then
                set firstImg to i
                exit repeat
            end if
            set i to i + 1
        end repeat
        set lastImg to 0
        if firstImg > 0 then
            set lastImg to firstImg
            set j to firstImg + 1
            repeat while j ≤ lastScan
                if (count of images of slide j of d) > 0 then
                    set lastImg to j
                else
                    exit repeat
                end if
                set j to j + 1
            end repeat
        end if
        return (firstImg as text) & " " & (lastImg as text)
    end tell
end run
