on run argv
    set outPath to item 1 of argv
    -- Save the open draft once, at the end of the build. The mutating/reading primitives no
    -- longer open/save the deck per call (open-once/save-once, #117) — they mutate `front
    -- document` in place — so this persists all of build()'s edits with a single disk write.
    --
    -- CRITICAL: save WITH the explicit outPath. `save_draft`'s `save … in outPath` does NOT
    -- rebind the open document — it stays bound to the *template*, so a bare `save front
    -- document` writes the week's edits back into master.key and corrupts it (the draft, written
    -- pristine at save_draft time, keeps no edits). Always pass the path so we write the draft,
    -- never the template. The draft stays open (the web app's post-build `open path` focuses it).
    tell application "Keynote"
        save front document in (POSIX file outPath)
    end tell
    return "ok"
end run
