on run argv
    set templatePath to item 1 of argv
    set outPath to item 2 of argv
    tell application "Keynote"
        activate  -- ensure the app is fully launched before the open event (avoids -609)
        -- Open via an ALIAS, not a bare `POSIX file`: on Keynote 14.4 / macOS 26.5 the bare form
        -- silently returns missing value (no doc opens) → "Can't make missing value into type
        -- specifier" (-1700) on the save below. The alias coercion hands sandboxed Keynote a
        -- usable file reference.
        set tmplDoc to open ((POSIX file templatePath) as alias)
        -- Write a pristine copy to outPath, then CLOSE the template and reopen the copy so the
        -- open `front document` is bound to the DRAFT, never the template. This is critical: the
        -- build mutates the open document in place (delete_slides, set_*_slide, …), and if a fill
        -- crashes before finalize, macOS autosave writes the open doc back to disk. With the doc
        -- bound to the draft, that autosave hits the draft; binding it to the template (the old
        -- behavior) silently corrupted master.key on every crashed build (#98 fallout).
        save tmplDoc in (POSIX file outPath)
        close tmplDoc saving no  -- never write the template, even if `save … in` rebound tmplDoc
        open ((POSIX file outPath) as alias)
    end tell
    return outPath
end run
