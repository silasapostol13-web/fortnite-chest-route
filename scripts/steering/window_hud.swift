import AppKit
import Carbon
import CoreGraphics

struct Snapshot: Decodable {
    let window: UInt32
    let chest: Int
    let turn: Double
    let meters: Int
}

final class Dial: NSView {
    var turn = 0.0

    override func draw(_ dirtyRect: NSRect) {
        let center = NSPoint(x: bounds.midX, y: bounds.midY)
        let gold = NSColor(calibratedRed: 1, green: 0.83, blue: 0.27, alpha: 1)
        gold.setStroke()
        NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1)).stroke()
        gold.setFill()
        let radians = -turn * Double.pi / 180
        let shape = [(0.0, 21.0), (14.0, -13.0), (0.0, -6.0), (-14.0, -13.0)]
        let arrow = NSBezierPath()
        for (i, point) in shape.enumerated() {
            let p = NSPoint(x: center.x + point.0 * cos(radians) - point.1 * sin(radians),
                            y: center.y + point.0 * sin(radians) + point.1 * cos(radians))
            if i == 0 { arrow.move(to: p) } else { arrow.line(to: p) }
        }
        arrow.close()
        arrow.fill()
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 270, height: 82),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
panel.level = .floating
panel.ignoresMouseEvents = true
panel.hidesOnDeactivate = false
panel.isOpaque = false
panel.backgroundColor = .clear
panel.contentView?.wantsLayer = true
panel.contentView?.layer?.backgroundColor = NSColor(calibratedWhite: 0.07, alpha: 0.90).cgColor
panel.contentView?.layer?.cornerRadius = 10
let dial = Dial(frame: NSRect(x: 12, y: 15, width: 52, height: 52))
panel.contentView?.addSubview(dial)

func label(_ string: String, y: Double, size: Double, color: NSColor) -> NSTextField {
    let text = NSTextField(labelWithString: string)
    text.font = .systemFont(ofSize: size, weight: .semibold)
    text.textColor = color
    text.frame = NSRect(x: 74, y: y, width: 190, height: 24)
    panel.contentView?.addSubview(text)
    return text
}

_ = label("PIRATE TOKEN HUNT", y: 53, size: 11, color: .systemYellow)
let title = label("", y: 29, size: 17, color: .white)
let detail = label("", y: 6, size: 13, color: .white)

func update(_ snapshot: Snapshot?) {
    guard let snapshot,
          let info = CGWindowListCopyWindowInfo(.optionIncludingWindow, snapshot.window) as? [[String: Any]],
          let window = info.first(where: { ($0[kCGWindowNumber as String] as? UInt32) == snapshot.window }),
          (window[kCGWindowIsOnscreen as String] as? Bool) == true,
          let bounds = window[kCGWindowBounds as String] as? [String: CGFloat],
          let x = bounds["X"], let y = bounds["Y"], let w = bounds["Width"], let h = bounds["Height"],
          let desktopTop = NSScreen.screens.first?.frame.maxY else {
        panel.orderOut(nil)
        return
    }
    panel.setFrameOrigin(NSPoint(x: x + (w - 270) / 2, y: desktopTop - y - h * 0.27))
    dial.turn = snapshot.turn
    dial.needsDisplay = true
    title.stringValue = "Chest \(snapshot.chest) · Dijkstra"
    let direction = abs(snapshot.turn) < 12 ? "Ahead" : snapshot.turn > 0 ? "Right" : "Left"
    detail.stringValue = snapshot.meters <= 5 ? "Search area" : "\(direction)  ·  ~\(snapshot.meters) m"
    dial.isHidden = snapshot.meters <= 5
    if !panel.isVisible {
        panel.orderFrontRegardless()
        FileHandle.standardError.write(Data("Live waypoint HUD shown on gameplay.\n".utf8))
    }
}

// Control-Option-N skips to the next chest, Control-Option-B goes back one. Carbon hot keys
// fire while Remote Play keeps focus and need no Accessibility permission.
var hotKeys: [EventHotKeyRef?] = []
var pressed = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
    var key = EventHotKeyID()
    GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                      MemoryLayout<EventHotKeyID>.size, nil, &key)
    print(key.id == 1 ? "next" : "back")
    fflush(stdout)
    return noErr
}, 1, &pressed, nil, nil)
for (id, code) in [(UInt32(1), kVK_ANSI_N), (UInt32(2), kVK_ANSI_B)] {
    var ref: EventHotKeyRef?
    RegisterEventHotKey(UInt32(code), UInt32(controlKey | optionKey), EventHotKeyID(signature: OSType(0x46544e54), id: id),
                        GetApplicationEventTarget(), 0, &ref)
    hotKeys.append(ref)
}

DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine() {
        let snapshot = try? JSONDecoder().decode(Snapshot.self, from: Data(line.utf8))
        DispatchQueue.main.async { update(snapshot) }
    }
    DispatchQueue.main.async { app.terminate(nil) }
}
app.run()
