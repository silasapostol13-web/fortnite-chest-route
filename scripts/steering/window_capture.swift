import AppKit
import CoreGraphics
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

func report(_ message: String) {
    FileHandle.standardError.write(Data((message + "\n").utf8))
}

final class VideoOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    let width: Int
    let height: Int
    private var packed: Data

    init(width: Int, height: Int) {
        self.width = width
        self.height = height
        self.packed = Data(count: width * height * 4)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        report("Window capture stopped: \(error.localizedDescription)")
        exit(1)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sample.isValid,
              let metadata = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]],
              let rawStatus = metadata.first?[.status] as? Int,
              SCFrameStatus(rawValue: rawStatus) == .complete,
              let pixels = CMSampleBufferGetImageBuffer(sample),
              CVPixelBufferGetWidth(pixels) == width,
              CVPixelBufferGetHeight(pixels) == height else { return }

        CVPixelBufferLockBaseAddress(pixels, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixels, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(pixels) else { return }
        let stride = CVPixelBufferGetBytesPerRow(pixels)
        packed.withUnsafeMutableBytes { destination in
            guard let target = destination.baseAddress else { return }
            for row in 0..<height {
                memcpy(target.advanced(by: row * width * 4), base.advanced(by: row * stride), width * 4)
            }
        }
        do {
            try FileHandle.standardOutput.write(contentsOf: packed)
        } catch {
            exit(0)
        }
    }
}

@main
struct WindowCapture {
    @MainActor
    static func main() async {
        _ = NSApplication.shared
        let mode = CommandLine.arguments.dropFirst().first ?? ""
        if mode == "--check-permission" {
            print(CGPreflightScreenCaptureAccess() ? "granted" : "required")
            return
        }
        if !CGPreflightScreenCaptureAccess() && !CGRequestScreenCaptureAccess() {
            report("Allow screen recording for your Terminal in System Settings > Privacy & Security > Screen & System Audio Recording, then reopen Terminal and retry.")
            exit(1)
        }
        do {
            let shareable = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false)
            let windows = shareable.windows.filter { $0.frame.width >= 320 && $0.frame.height >= 180 }
            if mode == "--list" {
                for window in windows {
                    print("\(window.windowID)\t\(window.owningApplication?.applicationName ?? "")\t\(window.title ?? "")\t\(window.isOnScreen)\t\(Int(window.frame.width))x\(Int(window.frame.height))")
                }
                return
            }
            let selected: SCWindow?
            if mode == "--remote-play" {
                selected = windows.filter {
                    let owner = $0.owningApplication?.applicationName.lowercased() ?? ""
                    let bundle = $0.owningApplication?.bundleIdentifier.lowercased() ?? ""
                    return owner.contains("remote play") || bundle.contains("remoteplay")
                }.max {
                    if $0.isOnScreen != $1.isOnScreen { return $1.isOnScreen }
                    return $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height
                }
            } else if let id = UInt32(mode) {
                selected = windows.first { $0.windowID == id }
            } else {
                report("Use --remote-play, --list, or an explicit window ID.")
                exit(2)
            }
            guard let window = selected else {
                report("No matching window is visible. Open the gameplay window and keep it unminimized.")
                exit(1)
            }
            let width = 1920
            let height = min(2160, max(180, Int((Double(width) * window.frame.height / window.frame.width).rounded())))
            let config = SCStreamConfiguration()
            config.width = width
            config.height = height
            config.pixelFormat = kCVPixelFormatType_32BGRA
            config.minimumFrameInterval = CMTime(value: 1, timescale: 30)
            config.queueDepth = 3
            config.showsCursor = false
            config.capturesAudio = false
            if #available(macOS 14.2, *) { config.ignoreShadowsSingleWindow = true }
            let output = VideoOutput(width: width, height: height)
            let stream = SCStream(filter: SCContentFilter(desktopIndependentWindow: window),
                                  configuration: config, delegate: output)
            try stream.addStreamOutput(output, type: .screen, sampleHandlerQueue: DispatchQueue(label: "gameplay-frames"))
            // The receiver reads exactly this header followed by tightly packed BGRA frames.
            FileHandle.standardOutput.write(Data("\(width) \(height) \(window.windowID)\n".utf8))
            report("Capturing only window \(window.windowID) from \(window.owningApplication?.applicationName ?? "selected app").")
            try await stream.startCapture()
            while true {
                try await Task.sleep(nanoseconds: 1_000_000_000)
                withExtendedLifetime((stream, output)) {}
            }
        } catch {
            report("Window capture failed: \(error.localizedDescription)")
            exit(1)
        }
    }
}
