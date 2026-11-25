import Foundation
import Vision

func readText(_ handler: VNImageRequestHandler) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    do {
        try handler.perform([request])
        return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " ")
    } catch { return "" }
}

if CommandLine.arguments.dropFirst().first == "--stream" {
    while let line = readLine() {
        let text = autoreleasepool {
            guard let bytes = Data(base64Encoded: line) else { return "" }
            return readText(VNImageRequestHandler(data: bytes))
        }
        print(text)
        fflush(stdout)
    }
} else {
    for path in CommandLine.arguments.dropFirst() {
        let url = URL(fileURLWithPath: path)
        print(url.lastPathComponent + "\t" + readText(VNImageRequestHandler(url: url)))
    }
}
