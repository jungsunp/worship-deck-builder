// The lines a string wraps to in a Keynote text box — measure_lines.swift's layout, returning
// the lines themselves instead of their count. `/prep-week` prints 교회소식 items this way so
// Claude sees where the slide breaks a phrase (`announce_suggest.py`).
//
// stdin:  JSON [{"text": "...", "font": "NanumGothicBold", "size": 80, "width": 1816}, ...]
// stdout: JSON [[line, ...], ...] — each line keeps its trailing "\n" when it ends a paragraph;
//         null where the font isn't installed
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
var out: [Any] = []
for item in items {
    guard let font = NSFont(name: item.font, size: item.size) else {
        out.append(NSNull())
        continue
    }
    let text = item.text as NSString
    let attributed = NSAttributedString(string: item.text, attributes: [.font: font])
    let framesetter = CTFramesetterCreateWithAttributedString(attributed)
    let path = CGPath(rect: CGRect(x: 0, y: 0, width: item.width, height: 100_000), transform: nil)
    let frame = CTFramesetterCreateFrame(framesetter, CFRange(location: 0, length: 0), path, nil)
    out.append((CTFrameGetLines(frame) as! [CTLine]).map { line -> String in
        let r = CTLineGetStringRange(line)
        return text.substring(with: NSRange(location: r.location, length: r.length))
    })
}
FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: out))
