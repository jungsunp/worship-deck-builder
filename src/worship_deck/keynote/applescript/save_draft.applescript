on run argv
    set templatePath to item 1 of argv
    set outPath to item 2 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        set tmplDoc to open (POSIX file templatePath)
        -- Write a pristine copy to outPath, then CLOSE the template and reopen the copy so the
        -- open `front document` is bound to the DRAFT, never the template. This is critical: the
        -- build mutates the open document in place (delete_slides, set_*_slide, …), and if a fill
        -- crashes before finalize, macOS autosave writes the open doc back to disk. With the doc
        -- bound to the draft, that autosave hits the draft; binding it to the template (the old
        -- behavior) silently corrupted master.key on every crashed build (#98 fallout).
        save tmplDoc in (POSIX file outPath)
        close tmplDoc saving no  -- never write the template, even if `save … in` rebound tmplDoc
        open (POSIX file outPath)
    end tell
    return outPath
end run
