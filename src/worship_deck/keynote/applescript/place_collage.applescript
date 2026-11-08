-- Turn the 1-based slide into a photo-only collage slide: blank every text box, then place each
-- photo at its exact (x, y, width). argv: keyPath, slideIndex, then groups of 4 per photo:
-- imagePath, x, y, width. Heights follow from Keynote's locked aspect ratio (the photos are
-- pre-shrunk with the same aspect the layout was computed from, so no cropping or stretching).
-- The slide is a duplicate of a 교회소식 item slide, so it already carries the dark background.
on run argv
    set slideIndex to (item 2 of argv) as integer
    tell application "Keynote"
        set d to front document
        set s to slide slideIndex of d
        repeat with t in (text items of s)
            set object text of t to ""
        end repeat
        set k to 3
        repeat while k + 3 ≤ (count of argv)
            set imgPath to item k of argv
            set px to (item (k + 1) of argv) as integer
            set py to (item (k + 2) of argv) as integer
            set pw to (item (k + 3) of argv) as integer
            tell s
                set img to make new image with properties {file:(POSIX file imgPath)}
            end tell
            set width of img to pw
            set position of img to {px, py}
            set k to k + 4
        end repeat
    end tell
    return "ok"
end run
