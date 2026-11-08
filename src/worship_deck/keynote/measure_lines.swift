// Line breaking for Keynote text boxes, the way Keynote does it: AppKit + CoreText.
//
// Keynote can't report overflow or a rendered size over AppleScript, so `build.py` asks this
// script how many lines a string wraps to at a given font/size/width and does the height math
// itself. Measured against the 2026-10-25 draft/final decks, CoreText's breaks match Keynote's
// PDF render character for character, Korean mid-word breaks included.
//
// stdin:  JSON [{"text": "...", "font": "NanumGothicBold", "size": 80, "width": 1816}, ...]
// stdout: JSON [line_count, ...]  — -1 where the font isn't installed
import AppKit
import CoreText
import Foundation

struct Item: Decodable {
    let text: String
    let font: String
    let size: Double
    let width: Double
}

let items = try JSONDecoder().decode([Item].self, from: FileHandle.standardInput.readDataToEndOfFile())
var counts: [Int] = []
for item in items {
    guard let font = NSFont(name: item.font, size: item.size) else {
        counts.append(-1)
        continue
    }
    let attributed = NSAttributedString(string: item.text, attributes: [.font: font])
    let framesetter = CTFramesetterCreateWithAttributedString(attributed)
    let path = CGPath(rect: CGRect(x: 0, y: 0, width: item.width, height: 100_000), transform: nil)
    let frame = CTFramesetterCreateFrame(framesetter, CFRange(location: 0, length: 0), path, nil)
    counts.append(CFArrayGetCount(CTFrameGetLines(frame)))
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: counts))
