import Foundation
import Vision
import AppKit
for path in CommandLine.arguments.dropFirst() {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    do {
        try VNImageRequestHandler(url: URL(fileURLWithPath: path)).perform([request])
        let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " ")
        print(URL(fileURLWithPath: path).lastPathComponent + "\t" + text)
    } catch { print(path + "\t") }
}
