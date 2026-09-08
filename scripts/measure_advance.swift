// The two numbers a Korean face has to bring with it, measured the way ProPresenter lays text out.
//
//   advance — mean Hangul glyph advance / font size. `layout.CHAR_W_KO` (0.83) is the deck-wide
//             estimate of this for Apple SD Gothic Neo; a face swap scales it by the ratio of the
//             two, or every width estimate in the deck is wrong by that ratio.
//   pitch   — one line's laid-out height / font size, i.e. `layout.LINE_PITCH` (1.21). Faces
//             differ here by a couple of percent, which is enough to overflow the tight boxes
//             (the 50pt lyric strips) by a point apiece.
//
// Companion to `measure_text.swift`, which measures a whole element rather than a face.
//
//     swift scripts/measure_advance.swift AppleSDGothicNeo-Regular Pretendard-Regular
//
// With no arguments it reports the faces the #247 review compared. A face has to be installed
// (~/Library/Fonts) for CoreText to find it by PostScript name — the same thing that has to be
// true on the church mini before a deck set in it renders there (#191/#197).
import AppKit
import CoreText
import Foundation

// Two sample sets, because the deck asks two different questions of a face.
//
// `headings` are the real section headings, which are what the keyed plate is sized around: short,
// all-Hangul, one space. That is `KEYED_CHAR_W_KO`.
//
// `body` is what `layout.CHAR_W_KO` actually estimates — 개역한글 scripture, a sung lyric line and a
// 교회 소식 notice, which carry the punctuation, digits and Latin that pull the average down. The two
// numbers differ by enough to matter: measured on headings alone, NanumSquare Round's ratio
// under-counted the notice plates and `audit_pro_layout.py` caught seven overflowing boxes.
let headings = ["회개로의 초대", "죄사함의 선포", "합심 기도", "봉헌 기도와 감사"]
let body = [
    "참 빛 곧 세상에 와서 각 사람에게 비취는 빛이 있었나니",
    "그가 세상에 계셨으며 세상은 그로 말미암아 지은 바 되었으되 세상이 그를 알지 못하였고",
    "주 하나님 지으신 모든 세계 내 마음 속에 그리어 볼 때",
    "다니엘 지상사 한국학교 개강 안내 (9월 13일 주일 오후 1시 30분, 문의: 교육부)",
]
// `layout.CHAR_W_EN`, which is a separate constant and needs separate scaling: the 교회 소식 rail
// rows are dates, dollar amounts and email addresses, and NanumSquare Round's Latin runs 8% wider
// than Apple SD Gothic Neo's even where its Hangul runs 4% wider.
let latin = [
    "9/20/2026~1/31/2027 (14)  1:20~3:20pm",
    "Zelle : missaera74@gmail.com",
    "O Lord my God, when I in awesome wonder",
    "and God saw that the light was good. ($160) ($150) ($140)",
]
// CoreText rounds a suggested frame size up to whole points, so measure at 1000pt: at 100 the
// pitch quantizes to 0.0025 em, and NanumSquare Round's real 1.1450 read back as 1.1400 — enough
// to leave a 교회 소식 plate 18pt short over eight lines.
let size: CGFloat = 1000
let names = CommandLine.arguments.count > 1
    ? Array(CommandLine.arguments.dropFirst())
    : ["AppleSDGothicNeo-Regular", "Pretendard-Regular", "SUIT-Regular",
       "NanumSquareRoundR", "IBMPlexSansKR-Regular", "GothicA1-Regular"]

for name in names {
    guard let font = NSFont(name: name, size: size) else {
        print("\(name)\tNOT INSTALLED")
        continue
    }
    func advance(_ samples: [String]) -> Double {
        var total = 0.0
        var chars = 0
        for sample in samples {
            let line = CTLineCreateWithAttributedString(
                NSAttributedString(string: sample, attributes: [.font: font]))
            total += Double(CTLineGetTypographicBounds(line, nil, nil, nil))
            chars += sample.count
        }
        return total / Double(chars) / Double(size)
    }
    // Pitch is the *inter-line* advance, so measure it as a difference. A one-line frame is
    // ascent + descent + this face's leading, which is not the same number — Apple SD Gothic Neo
    // happens to make them agree, and taking the one-line height for NanumSquare Round is what
    // sized its notice plates a line short.
    func height(_ lines: Int) -> Double {
        let text = Array(repeating: "가나다", count: lines).joined(separator: "\n")
        let framesetter = CTFramesetterCreateWithAttributedString(
            NSAttributedString(string: text, attributes: [.font: font]))
        return Double(CTFramesetterSuggestFrameSizeWithConstraints(
            framesetter, CFRange(location: 0, length: 0), nil,
            CGSize(width: CGFloat.greatestFiniteMagnitude,
                   height: CGFloat.greatestFiniteMagnitude), nil).height)
    }
    print(String(format: "%@\theading %.4f\tbody %.4f\tlatin %.4f\tpitch %.4f", name,
                 advance(headings), advance(body), advance(latin),
                 (height(5) - height(1)) / 4 / Double(size)))
}
