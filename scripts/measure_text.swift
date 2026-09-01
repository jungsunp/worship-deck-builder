// Ground-truth text measurement for `scripts/audit_pro_layout.py`.
//
// ProPresenter renders a text element by handing the element's RTF to AppKit and laying it out
// with CoreText, so the only way to know whether a generated slide really fits is to do the
// same thing to the same bytes. `styles._wrapped_height` is an estimate that has to stay
// conservative against this; when the two disagree, this one is right.
//
// One correction on top of CoreText: ProPresenter reserves the paragraph's line spacing after
// the *last* line as well, where `CTFramesetterSuggestFrameSizeWithConstraints` counts it only
// between lines. Measured against two decks the operator flagged by hand — with the trailing
// leading added, the elements this reports are exactly the ones ProPresenter marks "text box
// too small", and without it a box short by less than one line's leading looks fine here and
// warns in the app.
//
// stdin:  JSON [{"rtf": "<base64 of the element's rtf_data>", "width": 1744}, ...]
// stdout: JSON [height, ...]  — the height ProPresenter requires at that width
import AppKit
import CoreText
import Foundation

struct Item: Decodable {
    let rtf: String
    let width: Double
}

let input = FileHandle.standardInput.readDataToEndOfFile()
let items = try JSONDecoder().decode([Item].self, from: input)

var heights: [Double] = []
for item in items {
    guard let data = Data(base64Encoded: item.rtf),
          let attributed = NSAttributedString(rtf: data, documentAttributes: nil)
    else {
        heights.append(0)
        continue
    }
    let framesetter = CTFramesetterCreateWithAttributedString(attributed)
    let size = CTFramesetterSuggestFrameSizeWithConstraints(
        framesetter,
        CFRange(location: 0, length: 0),
        nil,
        CGSize(width: item.width, height: .greatestFiniteMagnitude),
        nil
    )
    var trailing = 0.0
    if attributed.length > 0,
       let style = attributed.attribute(.paragraphStyle, at: 0, effectiveRange: nil)
           as? NSParagraphStyle {
        trailing = style.lineSpacing
    }
    heights.append(Double(size.height) + trailing)
}

FileHandle.standardOutput.write(try JSONEncoder().encode(heights))
