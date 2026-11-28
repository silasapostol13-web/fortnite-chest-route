// Records the PS Remote Play window with the overlay HUD on top, at native (Retina) resolution, 60 fps, with the
// game's sound, straight to a .mov (ScreenCaptureKit's SCRecordingOutput, macOS 15+). Ctrl-C / SIGINT / SIGTERM
// finishes the file cleanly.
//
//   shoot-record --out take.mov [--window-id N] [--fps 60]
//
// Without --window-id it takes the largest on-screen PS Remote Play window. Only that window and the HUD's own
// windows (process "window-hud") are captured, so Terminal, notifications or anything else on top never show.
import AVFoundation
import AppKit
import CoreMedia
import Foundation
import ScreenCaptureKit

func say(_ s: String) { FileHandle.standardError.write(Data((s + "\n").utf8)) }

var out: URL?
var windowID: CGWindowID?
var hudPID: pid_t = -1
var fps = 60
var args = CommandLine.arguments.dropFirst().makeIterator()
while let a = args.next() {
    switch a {
    case "--out": out = URL(fileURLWithPath: args.next() ?? "")
    case "--window-id": windowID = CGWindowID(args.next() ?? "") ?? nil
    case "--hud-pid": hudPID = pid_t(args.next() ?? "") ?? -1
    case "--fps": fps = Int(args.next() ?? "") ?? 60
    default: say("unknown argument \(a)"); exit(2)
    }
}
guard let out else { say("usage: shoot-record --out take.mov [--window-id N] [--fps 60]"); exit(2) }

final class Recorder: NSObject, SCRecordingOutputDelegate, SCStreamDelegate, SCStreamOutput {
    var stream: SCStream?
    var finished = false
    func recordingOutputDidStartRecording(_ r: SCRecordingOutput) { say("Recording.") }
    func recordingOutput(_ r: SCRecordingOutput, didFailWithError error: Error) { say("Recording failed: \(error.localizedDescription)"); exit(1) }
    func recordingOutputDidFinishRecording(_ r: SCRecordingOutput) { say("Saved."); finished = true; exit(0) }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        // e.g. Remote Play closed mid-take: the file is still finished; give it a moment, then leave
        say("Capture stopped: \(error.localizedDescription)")
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { exit(self.finished ? 0 : 1) }
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {}
}

let recorder = Recorder()

Task {
    do {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        let target: SCWindow? = windowID.flatMap { id in content.windows.first { $0.windowID == id } } ?? content.windows
            .filter {
                let owner = $0.owningApplication?.applicationName.lowercased() ?? ""
                let bundle = $0.owningApplication?.bundleIdentifier.lowercased() ?? ""
                return owner.contains("remote play") || bundle.contains("remoteplay")
            }
            .max { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }
        guard let target else { say("No PS Remote Play window on screen. Open Remote Play first."); exit(1) }
        // The HUD panel is hidden until the overlay locks on (e.g. pre-game island), and a window filter is fixed at
        // start, so capture by APPLICATION: windows the HUD shows later are recorded too.
        let hudApps = content.applications.filter { $0.applicationName.contains("window-hud")
            || $0.bundleIdentifier.contains("window-hud") || $0.processID == hudPID }
        let hud = content.windows.filter { ($0.owningApplication?.applicationName ?? "").contains("window-hud") }
        if hudApps.isEmpty { say("Note: no HUD app found; recording the game only.") }
        let center = CGPoint(x: target.frame.midX, y: target.frame.midY)
        guard let display = content.displays.first(where: { $0.frame.contains(center) }) ?? content.displays.first else {
            say("No display."); exit(1)
        }
        let scale = NSScreen.screens.first {
            ($0.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber)?.uint32Value == display.displayID
        }?.backingScaleFactor ?? 2
        let filter = hudApps.isEmpty ? SCContentFilter(display: display, including: [target] + hud)
            : SCContentFilter(display: display, including: [target.owningApplication!] + hudApps, exceptingWindows: [])
        let config = SCStreamConfiguration()
        let rect = CGRect(x: target.frame.minX - display.frame.minX, y: target.frame.minY - display.frame.minY,
                          width: target.frame.width, height: target.frame.height)
        config.sourceRect = rect
        config.width = Int(rect.width * scale) / 2 * 2
        config.height = Int(rect.height * scale) / 2 * 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(fps))
        config.showsCursor = false
        config.queueDepth = 8
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48_000
        config.channelCount = 2
        let stream = SCStream(filter: filter, configuration: config, delegate: recorder)
        recorder.stream = stream
        try stream.addStreamOutput(recorder, type: .screen, sampleHandlerQueue: .global())
        try stream.addStreamOutput(recorder, type: .audio, sampleHandlerQueue: .global())
        let rc = SCRecordingOutputConfiguration()
        rc.outputURL = out
        rc.outputFileType = .mov
        rc.videoCodecType = .hevc
        let recording = SCRecordingOutput(configuration: rc, delegate: recorder)
        try stream.addRecordingOutput(recording)
        try await stream.startCapture()
        say("Capturing \(target.owningApplication?.applicationName ?? "?") window \(target.windowID) at \(config.width)x\(config.height), \(fps) fps, HUD apps \(hudApps.count) (windows now \(hud.count)), sound on -> \(out.path)")
    } catch {
        say("Could not start recording: \(error.localizedDescription)")
        say("If this mentions permission: System Settings > Privacy & Security > Screen & System Audio Recording > turn on Terminal.")
        exit(1)
    }
}

for sig in [SIGINT, SIGTERM] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler {
        say("Stopping...")
        Task {
            try? await recorder.stream?.stopCapture()     // finishes the file; recordingOutputDidFinishRecording exits
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            say("Stopped (no finish callback).")
            exit(0)
        }
    }
    source.resume()
    objc_setAssociatedObject(recorder, "\(sig)", source, .OBJC_ASSOCIATION_RETAIN)
}
RunLoop.main.run()
