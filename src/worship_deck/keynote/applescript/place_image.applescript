on run argv
    set keyPath to item 1 of argv
    set slideIndex to (item 2 of argv) as integer
    set imgPath to item 3 of argv
    -- Optional 4th arg "1": delete the slide's existing images first (replace, not stack) — used
    -- to swap last week's 봉헌 hymn page for this week's rather than layering on top of it.
    set clearExisting to ((count of argv) ≥ 4 and (item 4 of argv) is "1")
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set d to open (POSIX file keyPath)
        set slideW to width of d
        set slideH to height of d
        tell slide slideIndex of d
            if clearExisting then delete every image
            set img to make new image with properties {file:(POSIX file imgPath)}
        end tell
        -- Full-bleed by aspect-fill (cover): Keynote locks an image's aspect ratio, so we can't
        -- stretch. Scale the one dimension that makes the image cover the whole slide; the other
        -- overflows past the slide edge (clipped on export). Set only one side so the lock keeps
        -- it proportional, then center so the overflow is split evenly.
        if (width of img) / (height of img) < slideW / slideH then
            set width of img to slideW       -- narrower than slide: fill width, overflow height
        else
            set height of img to slideH      -- wider than slide: fill height, overflow width
        end if
        set finalW to width of img
        set finalH to height of img
        set position of img to {(slideW - finalW) / 2, (slideH - finalH) / 2}
        save d
        close d saving no
    end tell
    return "ok"
end run
