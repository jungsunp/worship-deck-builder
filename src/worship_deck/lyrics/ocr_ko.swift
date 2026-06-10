// Korean OCR for band lead-sheet images via Apple's Vision framework.
//
// Run (no compile step needed; requires Xcode Command Line Tools):
//     swift ocr_ko.swift <image>
//
// Prints recognized text lines top-to-bottom, left-to-right, one physical line per output
// line as "height<TAB>text" — height is the tallest observation in the line as a fraction
// of image height, so downstream can pick the page title (tallest Hangul line near the
// top) deterministically. Vision has high recall on Korean even over busy musical
// notation and never crashes on large images — unlike a local vision LLM. Line
// *reassembly* is done downstream by the text model in transcribe.py; this stage just
// extracts the raw text faithfully.

import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1 else {
    FileHandle.standardError.write("usage: ocr_ko.swift <image>\n".data(using: .utf8)!)
    exit(2)
}
guard let img = NSImage(contentsOfFile: args[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot load image: \(args[1])\n".data(using: .utf8)!)
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
try handler.perform([request])

// Vision splits each note's syllable group into its own observation. Group observations
// that share a baseline back into one physical line (sorted left-to-right), so downstream
// gets whole lyric lines ("내 주 를 가까이 더욱 가까이") instead of scattered fragments.
struct Box { let text: String; let midY: Double; let minX: Double; let height: Double }
let boxes = (request.results ?? []).compactMap { o -> Box? in
    guard let t = o.topCandidates(1).first else { return nil }
    return Box(text: t.string, midY: Double(o.boundingBox.midY), minX: Double(o.boundingBox.minX),
               height: Double(o.boundingBox.height))
}

let lineTolerance = 0.012   // fraction of image height; same line if midY within this
var lines: [[Box]] = []
for b in boxes.sorted(by: { $0.midY > $1.midY }) {
    if var last = lines.last, let ref = last.first, abs(ref.midY - b.midY) <= lineTolerance {
        last.append(b); lines[lines.count - 1] = last
    } else {
        lines.append([b])
    }
}
for line in lines {
    let height = line.map { $0.height }.max() ?? 0
    let text = line.sorted { $0.minX < $1.minX }.map { $0.text }.joined(separator: " ")
    print(String(format: "%.4f", height) + "\t" + text)
}
