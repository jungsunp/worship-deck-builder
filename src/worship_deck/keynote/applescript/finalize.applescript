on run argv
    set outPath to item 1 of argv
    -- Save the open draft once, at the end of the build. The mutating/reading primitives no
    -- longer open/save the deck per call (open-once/save-once, #117) — they mutate `front
    -- document` in place — so this persists all of build()'s edits with a single disk write.
    --
    -- `save_draft` reopened the draft copy, so the open `front document` is bound to the DRAFT
    -- (NOT the template) — see save_draft.applescript. So a PLAIN in-place `save` is both correct
    -- (it writes the draft, never master.key) and necessary: `save … in outPath` (even to the
    -- path the doc is already bound to) is an explicit save-to-path that leaves Keynote's autosave
    -- bookkeeping out of sync, so the next autosave on the still-open draft warns "changed by
    -- another application". A plain `save` keeps that bookkeeping consistent. The draft stays open
    -- (the web app's post-build `open path` focuses it).
    --
    -- outPath is still passed (build.py signature, logging) but intentionally unused here.
    tell application "Keynote"
        save front document
    end tell
    return "ok"
end run
