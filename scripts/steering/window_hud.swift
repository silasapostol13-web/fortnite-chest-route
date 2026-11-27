// Pirate Token Hunt HUD. One drawing path, two outputs:
//   window_hud                 click-through panel over the gameplay window (snapshots on stdin)
//   window_hud --render W H    one raw premultiplied BGRA frame on stdout per stdin line
// All art is drawn here in code with macOS system fonts. Layout is in a 1280x720 design space.
import AppKit
import Carbon
import CoreGraphics
import CoreText

/// A field that may arrive in a shape this build doesn't expect. A mismatch reads as "absent" instead of dropping the snapshot.
struct Soft<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) { value = try? T(from: decoder) }
}

struct Snapshot: Decodable {
    let window: UInt32?
    let chest: Int
    let turn: Double?
    let meters: Int?
    // Everything below is optional so the first protocol ({window, chest, turn, meters}) still works.
    let tracked: Bool?
    let done: Bool?
    let total: Int?
    let opened: Int?
    let kind: String?
    let heading: Double?      // compass heading, degrees
    let bearing: Double?      // straight-line bearing to the chest, degrees
    let player: [Double]?     // map units
    let target: [Double]?     // map units
    let path: [[Double]]?     // Dijkstra path, map units
    let mini: [Double]?       // minimap in 1920 px: player x, player y, px per map unit, x0, y0, x1, y1
    let compass: [Double]?    // compass strip in 1920 px: centre x, strip bottom y, px per degree
    let game: [Double]?       // gameplay rectangle inside the window, as fractions: x, y, w, h
    let ahead: Soft<[[Double]]>?   // old snapshots send this; not drawn any more
    let replanned: Soft<Bool>?     // true on the frame the chest order changed
    let rerouting: Soft<Bool>?     // true for a moment after he left the route and a new one was planned
    let nearby: Soft<Bool>?        // the next stop is a chest he's right next to, slotted in ahead of the route
    let style: String?        // old snapshots send this; there is one arrow now, so it is ignored
    let mpu: Double?          // metres per map unit
    let scale: Double?        // card size, 1 = default; grows down from under the compass
    let t: Double?            // media time; drives animation in --render
}

func rgb(_ r: Double, _ g: Double, _ b: Double, _ a: Double = 1) -> CGColor {
    CGColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: a)
}
func wrap(_ a: Double) -> Double { (a + 540).truncatingRemainder(dividingBy: 360) - 180 }
func clamp(_ v: Double, _ lo: Double, _ hi: Double) -> Double { min(max(v, lo), hi) }
func ease(_ p: Double) -> Double { let q = clamp(p, 0, 1); return 1 - pow(1 - q, 3) }

let goldHi = rgb(255, 226, 110), gold = rgb(255, 198, 52), goldLo = rgb(226, 128, 18)
let ink = rgb(22, 12, 4), navy = rgb(9, 16, 36), white = rgb(255, 255, 255)
let display = "Futura-CondensedExtraBold", label = "AvenirNextCondensed-HeavyItalic"
let space = CGColorSpace(name: CGColorSpace.sRGB)!

/// Closeness colour, cold to hot: pale gold far off, gold, orange, hot orange right at the chest (not red: red means danger in Fortnite). `flash` lifts it towards pale yellow.
func heatColor(_ h: Double, _ a: Double = 1, flash: Double = 0, shade: Double = 1) -> CGColor {
    let stops: [[Double]] = [[0, 236, 228, 200], [0.3, 255, 222, 70], [0.65, 255, 160, 30], [0.85, 255, 122, 18], [1, 255, 92, 8]]
    let x = clamp(h, 0, 1)
    var i = 1
    while i < stops.count - 1 && stops[i][0] < x { i += 1 }
    let lo = stops[i - 1], hi = stops[i], k = (x - lo[0]) / (hi[0] - lo[0]), f = clamp(flash, 0, 1)
    let pale = [255.0, 246, 196]
    let c = (0..<3).map { n -> Double in let v = lo[n + 1] + (hi[n + 1] - lo[n + 1]) * k; return v + (pale[n] - v) * f }
    return rgb(c[0] * shade, c[1] * shade, c[2] * shade, a)
}

final class Hud {
    // Latest good tracking state and smoothed values.
    var last: Snapshot?
    var lastTrackedAt = -1e9, shownAt = -1e9, drawnAt = -1e9
    var done = false, primed = false
    var angle = 0.0, pinAngle = 0.0, px = 0.0, py = 0.0
    var chest = -1, opened = -1, kind = ""
    var popAt = -1e9, slideAt = -1e9, rerouteAt = -1e9
    var wasRerouting = false               // the snapshot before this one had `rerouting`; the moment starts on the rising edge
    var shownMeters = -1.0                 // the distance on the card: eased towards each fix, held while tracking is lost
    var snapMeters = true                  // jump straight to the next fix (new chest, new target or a re-plan)
    var aim: [Double] = []                 // the chest position the distance belongs to
    var unit: CGFloat = 1
    var near = 0.0                         // 0 at 60 m or more from the chest, 1 at 6 m
    var beat = 0.0                         // pulse phase; runs faster the closer the chest is
    var throb = 0.0                        // 0...1 pulse built from `beat`
    var legStart = 0.0                     // metres to the chest when it became the active one (30...90); 0 = not set yet
    var progress = 0.0                     // smoothed share of this leg already covered; fills the heat bar

    func feed(_ snapshot: Snapshot?, at now: Double) {
        guard let s = snapshot else { return }
        let live = (s.tracked ?? true) && s.turn != nil && s.meters != nil
        if last == nil && !live { return }          // nothing shows before the first lock
        if chest >= 0 {
            if let o = s.opened, opened >= 0, o > opened { popAt = now }
            if s.chest != chest { slideAt = now; legStart = 0; snapMeters = true }
        }
        if s.replanned?.value == true { snapMeters = true }
        let rerouting = s.rerouting?.value == true
        if rerouting && !wasRerouting { rerouteAt = now; snapMeters = true; legStart = 0 }
        wasRerouting = rerouting
        if live, let target = s.target, target.count == 2 {
            if aim.count == 2 && hypot(target[0] - aim[0], target[1] - aim[1]) > 1 { snapMeters = true; legStart = 0 }
            aim = target
        }
        chest = s.chest
        opened = s.opened ?? opened
        kind = s.kind ?? kind
        done = s.done ?? false
        if live || done {
            if now - lastTrackedAt > 8.6 { shownAt = now; primed = false }
            if live { last = s }
            lastTrackedAt = now
        }
    }

    /// False once there is nothing to draw (never locked, or lost for a while).
    func visible(at now: Double) -> Bool { last != nil && now - lastTrackedAt < 8.6 }

    // MARK: drawing helpers

    @discardableResult
    func text(_ ctx: CGContext, _ string: String, _ font: String, _ size: CGFloat, x: CGFloat, y: CGFloat,
              align: CGFloat = 0, color: CGColor = white, outline: CGFloat = 0, kern: CGFloat = 0,
              shear: CGFloat = 0, glow: CGColor? = nil) -> CGFloat {
        let attributes: [NSAttributedString.Key: Any] = [
            NSAttributedString.Key(kCTFontAttributeName as String): CTFontCreateWithName(font as CFString, size, nil),
            NSAttributedString.Key(kCTForegroundColorFromContextAttributeName as String): true,
            NSAttributedString.Key(kCTKernAttributeName as String): kern,
        ]
        let line = CTLineCreateWithAttributedString(NSAttributedString(string: string, attributes: attributes))
        let width = CGFloat(CTLineGetTypographicBounds(line, nil, nil, nil)) - kern
        ctx.saveGState()
        ctx.textMatrix = CGAffineTransform(a: 1, b: 0, c: shear, d: -1, tx: 0, ty: 0)
        let start = CGPoint(x: x - width * align, y: y)
        if outline > 0 {
            if let glow {
                ctx.setShadow(offset: .zero, blur: 9 * unit, color: glow)
            } else {
                ctx.setShadow(offset: CGSize(width: 0, height: -1.5 * unit), blur: 3 * unit, color: rgb(0, 0, 0, 0.55))
            }
            ctx.setTextDrawingMode(.stroke)
            ctx.setLineWidth(outline * 2)
            ctx.setLineJoin(.round)
            ctx.setStrokeColor(rgb(8, 10, 24, 0.95))
            ctx.textPosition = start
            CTLineDraw(line, ctx)
            ctx.setShadow(offset: .zero, blur: 0, color: nil)
        }
        ctx.setTextDrawingMode(.fill)
        ctx.setFillColor(color)
        ctx.textPosition = start
        CTLineDraw(line, ctx)
        ctx.restoreGState()
        return width
    }

    func gradient(_ ctx: CGContext, _ path: CGPath, _ colors: [CGColor], from: CGPoint, to: CGPoint) {
        ctx.saveGState()
        ctx.addPath(path)
        ctx.clip()
        let g = CGGradient(colorsSpace: space, colors: colors as CFArray, locations: nil)!
        ctx.drawLinearGradient(g, start: from, end: to, options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
        ctx.restoreGState()
    }

    func slab(_ x0: CGFloat, _ y0: CGFloat, _ x1: CGFloat, _ y1: CGFloat, lean: CGFloat) -> CGPath {
        let p = CGMutablePath()
        p.move(to: CGPoint(x: x0 + lean, y: y0))
        p.addLine(to: CGPoint(x: x1 + lean, y: y0))
        p.addLine(to: CGPoint(x: x1, y: y1))
        p.addLine(to: CGPoint(x: x0, y: y1))
        p.closeSubpath()
        return p
    }

    /// The pirate token: a gold doubloon. Large ones carry a skull and crossbones, small ones an X.
    func coin(_ ctx: CGContext, _ c: CGPoint, _ r: CGFloat, skull: Bool) {
        ctx.saveGState()
        ctx.setShadow(offset: CGSize(width: 0, height: -1 * unit), blur: 3 * unit, color: rgb(0, 0, 0, 0.6))
        ctx.setFillColor(ink)
        ctx.fillEllipse(in: CGRect(x: c.x - r - 1.6, y: c.y - r - 1.6, width: 2 * r + 3.2, height: 2 * r + 3.2))
        ctx.restoreGState()
        let disc = CGPath(ellipseIn: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r), transform: nil)
        gradient(ctx, disc, [goldHi, gold, goldLo], from: CGPoint(x: c.x - r * 0.5, y: c.y - r), to: CGPoint(x: c.x + r * 0.5, y: c.y + r))
        ctx.setStrokeColor(rgb(150, 78, 8, 0.9))
        ctx.setLineWidth(max(0.8, r * 0.09))
        ctx.strokeEllipse(in: CGRect(x: c.x - r * 0.8, y: c.y - r * 0.8, width: r * 1.6, height: r * 1.6))
        let dark = rgb(92, 44, 6)
        ctx.setStrokeColor(dark)
        ctx.setFillColor(dark)
        ctx.setLineCap(.round)
        if !skull {
            ctx.setLineWidth(max(1.6, r * 0.26))
            let d = r * 0.36
            ctx.strokeLineSegments(between: [CGPoint(x: c.x - d, y: c.y - d), CGPoint(x: c.x + d, y: c.y + d),
                                             CGPoint(x: c.x + d, y: c.y - d), CGPoint(x: c.x - d, y: c.y + d)])
            return
        }
        ctx.setLineWidth(r * 0.15)
        ctx.strokeLineSegments(between: [CGPoint(x: c.x - r * 0.5, y: c.y + r * 0.08), CGPoint(x: c.x + r * 0.5, y: c.y + r * 0.56),
                                         CGPoint(x: c.x + r * 0.5, y: c.y + r * 0.08), CGPoint(x: c.x - r * 0.5, y: c.y + r * 0.56)])
        ctx.fillEllipse(in: CGRect(x: c.x - r * 0.42, y: c.y - r * 0.56, width: r * 0.84, height: r * 0.74))
        ctx.addPath(CGPath(roundedRect: CGRect(x: c.x - r * 0.24, y: c.y - r * 0.02, width: r * 0.48, height: r * 0.36),
                           cornerWidth: r * 0.08, cornerHeight: r * 0.08, transform: nil))
        ctx.fillPath()
        ctx.setFillColor(goldHi)
        for side in [-1.0, 1.0] {
            ctx.fillEllipse(in: CGRect(x: c.x + CGFloat(side) * r * 0.18 - r * 0.11, y: c.y - r * 0.30, width: r * 0.22, height: r * 0.24))
        }
        ctx.move(to: CGPoint(x: c.x, y: c.y - r * 0.02))
        ctx.addLine(to: CGPoint(x: c.x - r * 0.06, y: c.y + r * 0.10))
        ctx.addLine(to: CGPoint(x: c.x + r * 0.06, y: c.y + r * 0.10))
        ctx.fillPath()
        ctx.setStrokeColor(goldHi)
        ctx.setLineWidth(r * 0.04)
        ctx.strokeLineSegments(between: [CGPoint(x: c.x - r * 0.08, y: c.y + r * 0.18), CGPoint(x: c.x - r * 0.08, y: c.y + r * 0.32),
                                         CGPoint(x: c.x + r * 0.08, y: c.y + r * 0.18), CGPoint(x: c.x + r * 0.08, y: c.y + r * 0.32)])
    }

    // MARK: frame

    func draw(_ ctx: CGContext, width: CGFloat, height: CGFloat, at now: Double) {
        let dt = clamp(now - drawnAt, 0, 0.25)
        drawnAt = now
        guard let s = last, visible(at: now) else { return }
        let lostFor = now - lastTrackedAt
        let live = lostFor < 0.5 && !done
        let scanning = !live && !done
        let fade = clamp((8.6 - lostFor) / 0.6, 0, 1) * clamp((now - shownAt) / 0.25, 0, 1)
        let turn = s.turn ?? 0
        // Distance: ease towards each new fix so one noisy position can't make it jump; `last` is the last tracked
        // snapshot, so the number holds while tracking is lost.
        let fix = Double(s.meters ?? 0)
        if snapMeters || shownMeters < 0 { shownMeters = fix; snapMeters = false }
        else { shownMeters += (fix - shownMeters) * (1 - exp(-dt / 0.3)) }
        let meters = Int(shownMeters.rounded())
        let search = live && meters <= 5 && !(now >= rerouteAt && now < rerouteAt + 2.4)   // never DIG HERE over the reroute word

        // Smooth the needle, the compass pin and the minimap position between snapshots.
        let pinTarget = wrap((s.bearing ?? 0) - (s.heading ?? 0))
        let me = s.player ?? [0, 0]
        if !primed || abs(me[0] - px) + abs(me[1] - py) > 60 {
            angle = turn; pinAngle = pinTarget; px = me[0]; py = me[1]; primed = true
        } else if live {
            angle += wrap(turn - angle) * (1 - exp(-dt / 0.10))
            pinAngle += wrap(pinTarget - pinAngle) * (1 - exp(-dt / 0.10))
            let k = 1 - exp(-dt / 0.22)
            px += (me[0] - px) * k
            py += (me[1] - py) * k
        }
        angle = wrap(angle)
        pinAngle = wrap(pinAngle)

        let pop = now - popAt                      // seconds since a chest was opened
        let popping = pop >= 0 && pop < 1.3
        // REROUTING moment: he left the route (or opened a chest that was off it) and a new route was planned.
        // 1.3 s: the word, a turning route icon and a blue plate; then the arrow comes back under NEW ROUTE.
        // After a chest pop it waits for CHEST OPENED! to finish and runs shorter.
        let afterPop = rerouteAt >= popAt && rerouteAt < popAt + 1.05
        let rerouteStart = afterPop ? popAt + 1.05 : rerouteAt
        let rerouteEnd = rerouteStart + (afterPop ? 0.9 : 1.3)
        let re = now - rerouteStart
        let rerouting = live && !done && re >= 0 && now < rerouteEnd
        let fresh = live && !rerouting && now >= rerouteEnd && now < rerouteEnd + 1.6   // the new route's first moments
        near = (live || scanning) && !search && !rerouting ? clamp((60 - shownMeters) / 54, 0, 1) : 0
        beat += dt * (0.8 + 2.2 * near * near)       // 0.8 pulses a second far away, 3 a second at the chest
        throb = search ? abs(sin(now * 4)) : pow(abs(sin(beat * .pi)), 1.5)
        // Heat bar: how much of this leg is covered, measured from where the chest became the active one.
        if live { legStart = legStart == 0 ? clamp(shownMeters, 30, 90) : min(90, max(legStart, shownMeters)) }
        let covered = rerouting ? 0 : done || search || popping ? 1 : live && legStart > 5 ? clamp((legStart - shownMeters) / (legStart - 5), 0, 1) : progress
        progress += (covered - progress) * (1 - exp(-dt / 0.15))
        let hot = search ? 1 : scanning ? 0.5 * near : near   // drives the card's edge glow
        func hotColor(_ a: Double, flash: Double = 0) -> CGColor {
            search ? rgb(255, 226 + 20 * flash, 110 + 86 * flash, a) : heatColor(near, a, flash: flash)
        }
        unit = width / 1280
        ctx.saveGState()
        ctx.translateBy(x: 0, y: height)
        ctx.scaleBy(x: unit, y: -unit)
        ctx.setAlpha(CGFloat(fade))

        let slide = now - (popping ? popAt + 1.05 : rerouting ? rerouteStart : max(slideAt, now >= rerouteEnd ? rerouteEnd : -1e9))

        if live && s.bearing != nil && s.heading != nil { compassPin(ctx, s, alpha: fade) }
        if live && s.player != nil && s.target != nil { minimap(ctx, s, drawn: rerouting || fresh ? ease(re / 0.8) : 1) }

        // Card: needle dial on the left, slanted plate on the right, centred under the compass.
        ctx.saveGState()
        let appear = ease((now - shownAt) / 0.3)
        let bump = 0.92 + 0.08 * appear + (popping ? 0.07 * sin(.pi * clamp(pop / 0.3, 0, 1)) : 0)
            + (rerouting ? 0.06 * sin(.pi * clamp(re / 0.3, 0, 1)) : 0) + (fresh ? 0.05 * sin(.pi * clamp((now - rerouteEnd) / 0.3, 0, 1)) : 0)
        let size = CGFloat(clamp(s.scale ?? 1, 0.6, 1.6))
        ctx.translateBy(x: 639, y: 62)
        ctx.scaleBy(x: size, y: size)
        ctx.translateBy(x: 0, y: 47)
        ctx.scaleBy(x: CGFloat(bump), y: CGFloat(bump))
        ctx.translateBy(x: -639, y: -109)

        let plate = slab(476, 68, 786, 157, lean: 10)   // stops short of the game's storm banner
        if hot > 0.02 && !popping {                  // closeness: the card's edge glows hotter and throbs
            ctx.saveGState()
            ctx.setShadow(offset: .zero, blur: CGFloat(4 + 18 * hot * (0.55 + 0.45 * throb)) * unit, color: hotColor(0.4 + 0.6 * hot))
            ctx.addPath(plate)
            ctx.setStrokeColor(hotColor(0.95))
            ctx.setLineWidth(CGFloat(1 + 3.5 * hot))
            ctx.strokePath()
            ctx.restoreGState()
        }
        ctx.saveGState()
        ctx.setShadow(offset: CGSize(width: 0, height: -3 * unit), blur: 10 * unit, color: rgb(0, 0, 0, 0.5))
        ctx.addPath(plate)
        ctx.setFillColor(rgb(9, 16, 36, 0.66))
        ctx.fillPath()
        ctx.restoreGState()
        gradient(ctx, plate, [rgb(16, 30, 66, 0.45), rgb(34, 14, 62, 0.45)], from: CGPoint(x: 476, y: 68), to: CGPoint(x: 796, y: 150))
        gradient(ctx, slab(476 + 9.5, 68, 786 + 9.5, 72, lean: 0.5), [goldHi, gold, goldLo], from: CGPoint(x: 476, y: 0), to: CGPoint(x: 796, y: 0))
        let flood = pow(near, 1.15) * (scanning ? 0.5 : 1)   // closeness: the whole plate floods from navy to amber to hot orange
        if flood > 0.01 && !popping {
            ctx.addPath(plate)
            ctx.setFillColor(heatColor(near, 0.9 * flood, flash: 0.12 * near * throb, shade: 0.78))
            ctx.fillPath()
        }
        if rerouting {                              // same navy plate, a touch darker so the word carries, with a pale-gold edge that breathes
            let breath = 0.5 + 0.5 * sin(re * 2 * .pi / 0.65)
            ctx.addPath(plate)
            ctx.setFillColor(rgb(6, 12, 30, 0.28))
            ctx.fillPath()
            gradient(ctx, slab(476 + 9.5, 68, 786 + 9.5, 72, lean: 0.5), [goldHi, gold, goldLo], from: CGPoint(x: 476, y: 0), to: CGPoint(x: 796, y: 0))
            ctx.saveGState()
            ctx.setShadow(offset: .zero, blur: CGFloat(6 + 6 * breath) * unit, color: rgb(255, 226, 110, 0.75))
            ctx.addPath(plate)
            ctx.setStrokeColor(rgb(255, 236, 160, 0.55 + 0.4 * breath))
            ctx.setLineWidth(2)
            ctx.strokePath()
            ctx.restoreGState()
        }
        let flashAt = rerouting ? re : fresh ? now - rerouteEnd : 9
        if flashAt < 0.5 {                          // a light sweep as the moment starts, and again as the new route lands
            ctx.saveGState()
            ctx.addPath(plate)
            ctx.clip()
            let sweep = CGFloat(476 + 390 * clamp(flashAt / 0.4, 0, 1))
            ctx.setFillColor(rgb(255, 226, 110, 0.55 * (1 - clamp(flashAt / 0.5, 0, 1))))
            ctx.addPath(slab(sweep - 150, 68, sweep, 157, lean: 26))
            ctx.fillPath()
            ctx.restoreGState()
        }
        if popping {                                // gold flash across the plate
            ctx.saveGState()
            ctx.addPath(plate)
            ctx.clip()
            let sweep = CGFloat(476 + 390 * clamp(pop / 0.45, 0, 1))
            ctx.setFillColor(rgb(255, 226, 110, 0.55 * (1 - clamp(pop / 0.5, 0, 1))))
            ctx.addPath(slab(sweep - 150, 68, sweep, 157, lean: 26))
            ctx.fillPath()
            ctx.restoreGState()
        }
        ctx.addPath(plate)
        ctx.setStrokeColor(rerouting ? rgb(255, 236, 160, 0.9) : hot > 0.02 && !popping ? hotColor(0.35 + 0.65 * hot, flash: 0.5 * hot * throb) : rgb(255, 255, 255, 0.16))
        ctx.setLineWidth(CGFloat(1 + 2 * hot))
        ctx.strokePath()

        text(ctx, "PIRATE TOKEN HUNT", label, 14.5, x: 552, y: 91, color: gold, outline: 1.2, kern: 1.1)

        // Middle row: what is next and how far it is. The distance is the hero: 30 pt and cold at 60 m,
        // 52 pt and pale-hot at 6 m, beating faster on the way in. It stays (dimmed) while tracking is lost.
        let enter = CGFloat(1 - ease(slide / 0.28)) * 16
        let announcing = popping && pop < 1.05
        if done {
            text(ctx, "ROUTE COMPLETE", display, 31, x: 550, y: 126, color: goldHi, outline: 2, shear: 0.12)
        } else if announcing {
            text(ctx, "CHEST OPENED!", display, 27, x: 550, y: 126, color: goldHi, outline: 2, shear: 0.12)
        } else if rerouting {                       // one word, as big as the plate allows, with three dots counting up
            ctx.saveGState()                        // slides in at full strength: no fade, so every frame of it is crisp
            let w = text(ctx, "REROUTING", display, 34, x: 548 + enter, y: 125.5, color: white, outline: 2.4, shear: 0.12)
            for i in 0..<3 {                        // always three, one lit at a time, so any single frame looks finished
                let lit = Int(re / 0.2) % 3 == i
                let c = CGPoint(x: 548 + enter + w + 8 + CGFloat(i) * 10.5, y: 121.8)
                ctx.setFillColor(rgb(8, 10, 24, 0.95))
                ctx.fillEllipse(in: CGRect(x: c.x - 5, y: c.y - 5, width: 10, height: 10))
                ctx.setFillColor(lit ? white : rgb(255, 255, 255, 0.45))
                ctx.fillEllipse(in: CGRect(x: c.x - 3.2, y: c.y - 3.2, width: 6.4, height: 6.4))
            }
            ctx.restoreGState()
        } else {
            ctx.saveGState()
            ctx.setAlpha(CGFloat(fade) * (1 - enter / 16))
            let nearbyChest = s.nearby?.value == true
            if scanning {
                text(ctx, "FINDING SIGNAL", display, 22, x: 550, y: 123, color: rgb(190, 204, 232), outline: 2, shear: 0.12)
            } else {
                text(ctx, search ? (kind == "buried" ? "DIG HERE!" : "OPEN IT!") : fresh ? "NEW ROUTE" : nearbyChest ? "CHEST NEARBY" : "NEXT CHEST", display, search ? 31 : 25, x: 550 + enter,
                     y: search ? 126 : 123, color: search || fresh || nearbyChest ? goldHi : white, outline: 2, shear: 0.12)
            }
            if !search {
                if scanning { ctx.setAlpha(CGFloat(fade) * 0.5) }
                let big = CGFloat((30 + 22 * near) * (1 + (scanning ? 0 : (0.03 + 0.09 * near) * throb)))
                let tint = heatColor(near, flash: min(1, 0.85 * flood + 0.4 * near * throb))   // pales as the plate floods, so it stays readable
                let halo = near > 0.05 && !scanning ? heatColor(near, 0.35 + 0.6 * near, flash: 0.5 * flood) : nil
                let m = text(ctx, "m", display, big * 0.55, x: 790 + enter, y: 128, align: 1, color: tint, outline: 2, shear: 0.12)
                text(ctx, "\(meters)", display, big, x: 790 + enter - m - 1, y: 128, align: 1,
                     color: tint, outline: 2.4, shear: 0.12, glow: halo)
            }
            ctx.restoreGState()
        }

        // Bottom row: what to do.
        let side = angle > 0 ? "RIGHT" : "LEFT"
        let action = done ? "EVERY CHEST CHECKED" : announcing ? "ON TO THE NEXT ONE" : rerouting ? "OFF ROUTE  ·  FINDING A NEW ROUTE" : scanning ? "READING COMPASS + MINIMAP"
            : search ? "X MARKS THE SPOT"
            : abs(angle) < 15 ? "STRAIGHT AHEAD" : abs(angle) > 135 ? "BEHIND YOU  ·  TURN \(side)"
            : abs(angle) < 45 ? "SLIGHT \(side)" : "TURN \(side)"
        text(ctx, action, label, rerouting ? 12.6 : 15, x: 550, y: rerouting ? 142 : 141.5,
             color: abs(angle) < 15 && live && !search && !rerouting ? goldHi : rgb(236, 240, 252), outline: 1.1, kern: 0.7)

        // Heat bar: fills towards the token as this leg is covered, gold at the start and hot orange at the end.
        let segments = 14
        let step = (768.0 - 550.0) / Double(segments)
        ctx.addPath(slab(547.5, 145.5, 770.5, 154.5, lean: 2))
        ctx.setFillColor(rgb(4, 6, 16, 0.7))
        ctx.fillPath()
        for i in 0..<segments {
            let x0 = CGFloat(550 + step * Double(i))
            let lit = scanning ? 0 : clamp(progress * Double(segments) - Double(i), 0, 1)
            let leading = lit > 0 && progress * Double(segments) < Double(i + 1) + 0.999 && !done
            ctx.addPath(slab(x0, 147, x0 + CGFloat(step) - 2, 153, lean: 1.6))
            ctx.setFillColor(lit > 0 ? (done || search ? rgb(255, 226, 110, 0.6 + 0.4 * throb)
                                        : heatColor(0.3 + 0.7 * (Double(i) + 0.5) / Double(segments), 0.25 + 0.75 * lit, flash: leading ? 0.8 * throb : 0.08))
                             : rgb(255, 255, 255, 0.15))
            ctx.fillPath()
        }
        coin(ctx, CGPoint(x: 778.5, y: 150), 6.5 + (progress > 0.9 ? 1.2 * throb : 0), skull: false)

        dial(ctx, CGPoint(x: 492, y: 111), search: search || done, scanning: scanning, now: now, pop: popping ? pop : nil,
             reroute: rerouting ? re : nil)
        ctx.restoreGState()
        ctx.restoreGState()
    }

    func dial(_ ctx: CGContext, _ c: CGPoint, search: Bool, scanning: Bool, now: Double, pop: Double?, reroute: Double? = nil) {
        let r: CGFloat = 46
        if let pop {                                 // ring and sparks when a chest is opened
            let p = clamp(pop / 0.7, 0, 1)
            ctx.setStrokeColor(rgb(255, 226, 110, 0.9 * (1 - p)))
            ctx.setLineWidth(CGFloat(6 * (1 - p) + 1))
            let ring = r + CGFloat(40 * ease(p))
            ctx.strokeEllipse(in: CGRect(x: c.x - ring, y: c.y - ring, width: 2 * ring, height: 2 * ring))
            ctx.setFillColor(rgb(255, 240, 170, 1 - p))
            for i in 0..<8 {
                let a = Double(i) * .pi / 4 + 0.4
                let d = Double(r) + 52 * ease(p)
                let q = CGPoint(x: c.x + CGFloat(cos(a) * d), y: c.y + CGFloat(sin(a) * d))
                let size = CGFloat(5 * (1 - p) + 1)
                ctx.move(to: CGPoint(x: q.x, y: q.y - size))
                ctx.addLine(to: CGPoint(x: q.x + size * 0.6, y: q.y))
                ctx.addLine(to: CGPoint(x: q.x, y: q.y + size))
                ctx.addLine(to: CGPoint(x: q.x - size * 0.6, y: q.y))
                ctx.fillPath()
            }
        }
        if near > 0.05 && !search && !scanning {      // every style: a halo behind the dial that heats up and throbs faster
            let halo = r + 2 + CGFloat((2 + 5 * near) * throb)
            ctx.saveGState()
            ctx.setShadow(offset: .zero, blur: CGFloat(6 + 16 * near) * unit, color: heatColor(near, 0.95))
            ctx.setFillColor(heatColor(near, 0.25 + 0.7 * near))
            ctx.fillEllipse(in: CGRect(x: c.x - halo, y: c.y - halo, width: 2 * halo, height: 2 * halo))
            ctx.restoreGState()
        }
        ctx.saveGState()
        ctx.setShadow(offset: CGSize(width: 0, height: -3 * unit), blur: 9 * unit, color: rgb(0, 0, 0, 0.6))
        ctx.setFillColor(rgb(8, 13, 30, 0.94))
        ctx.fillEllipse(in: CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
        ctx.restoreGState()
        let face = CGPath(ellipseIn: CGRect(x: c.x - r + 5, y: c.y - r + 5, width: 2 * r - 10, height: 2 * r - 10), transform: nil)
        gradient(ctx, face, [rgb(28, 46, 96, 0.9), rgb(12, 16, 40, 0.9)], from: CGPoint(x: c.x, y: c.y - r), to: CGPoint(x: c.x, y: c.y + r))
        // Compass rose (only when no arrow is shown; the arrow lies on its own tilted ground) and hour ticks.
        ctx.setFillColor(rgb(255, 255, 255, 0.07))
        for i in 0..<4 where search || scanning || reroute != nil {
            let a = Double(i) * .pi / 2
            let tip = CGPoint(x: c.x + CGFloat(sin(a)) * 34, y: c.y - CGFloat(cos(a)) * 34)
            let left = CGPoint(x: c.x + CGFloat(sin(a - 1.2)) * 8, y: c.y - CGFloat(cos(a - 1.2)) * 8)
            let right = CGPoint(x: c.x + CGFloat(sin(a + 1.2)) * 8, y: c.y - CGFloat(cos(a + 1.2)) * 8)
            ctx.move(to: tip); ctx.addLine(to: left); ctx.addLine(to: right); ctx.fillPath()
        }
        ctx.setStrokeColor(rgb(255, 214, 90, 0.55))
        ctx.setLineWidth(1.6)
        for i in 1..<12 {
            let a = Double(i) * .pi / 6
            ctx.strokeLineSegments(between: [CGPoint(x: c.x + CGFloat(sin(a)) * 33, y: c.y - CGFloat(cos(a)) * 33),
                                             CGPoint(x: c.x + CGFloat(sin(a)) * 37, y: c.y - CGFloat(cos(a)) * 37)])
        }
        // Gold rim.
        ctx.saveGState()
        let rim = CGMutablePath()
        rim.addEllipse(in: CGRect(x: c.x - r + 1, y: c.y - r + 1, width: 2 * r - 2, height: 2 * r - 2))
        rim.addEllipse(in: CGRect(x: c.x - r + 6, y: c.y - r + 6, width: 2 * r - 12, height: 2 * r - 12))
        ctx.addPath(rim)
        ctx.clip(using: .evenOdd)
        let g = CGGradient(colorsSpace: space, colors: [goldHi, gold, goldLo] as CFArray, locations: nil)!
        ctx.drawLinearGradient(g, start: CGPoint(x: c.x - r, y: c.y - r), end: CGPoint(x: c.x + r, y: c.y + r), options: [])
        ctx.restoreGState()
        // "Straight ahead" notch at the top of the rim.
        ctx.setFillColor(white)
        ctx.setStrokeColor(ink)
        ctx.setLineWidth(1.2)
        ctx.move(to: CGPoint(x: c.x, y: c.y - r + 12))
        ctx.addLine(to: CGPoint(x: c.x - 6, y: c.y - r + 1))
        ctx.addLine(to: CGPoint(x: c.x + 6, y: c.y - r + 1))
        ctx.closePath()
        ctx.drawPath(using: .fillStroke)

        if let reroute {                              // two arrows chasing each other round: a new route is being worked out
            let spin = reroute * 4.2 + 0.5, radius = 21.0, sweep = 2.15
            ctx.saveGState()
            ctx.setLineCap(.round)
            ctx.setLineJoin(.round)
            for (stroke, extra) in [(ink, 4.4), (goldHi, 0.0)] {
                ctx.saveGState()
                if extra > 0 { ctx.setShadow(offset: .zero, blur: 7 * unit, color: rgb(255, 200, 60, 0.9)) }
                for half in 0..<2 {
                    let a0 = spin + Double(half) * .pi, a1 = a0 + sweep
                    ctx.addArc(center: c, radius: CGFloat(radius), startAngle: CGFloat(a0), endAngle: CGFloat(a1), clockwise: false)
                    ctx.setStrokeColor(stroke)
                    ctx.setLineWidth(CGFloat(7.5 + extra))
                    ctx.strokePath()
                    // Arrow head at the leading end, pointing along the turn.
                    let tipA = a1 + 0.62, head = 11.5 + extra * 0.55
                    let tip = CGPoint(x: c.x + CGFloat(cos(tipA) * radius), y: c.y + CGFloat(sin(tipA) * radius))
                    let inner = CGPoint(x: c.x + CGFloat(cos(a1) * (radius - head)), y: c.y + CGFloat(sin(a1) * (radius - head)))
                    let outer = CGPoint(x: c.x + CGFloat(cos(a1) * (radius + head)), y: c.y + CGFloat(sin(a1) * (radius + head)))
                    ctx.move(to: tip); ctx.addLine(to: inner); ctx.addLine(to: outer); ctx.closePath()
                    ctx.setFillColor(stroke)
                    ctx.fillPath()
                }
                ctx.restoreGState()
            }
            ctx.restoreGState()
            return
        }
        if search {
            let pulse = CGFloat(abs(sin(now * 4)))
            ctx.setStrokeColor(rgb(255, 226, 110, 0.35 + 0.5 * Double(pulse)))
            ctx.setLineWidth(2.5)
            let ring = 30 + 4 * pulse
            ctx.strokeEllipse(in: CGRect(x: c.x - ring, y: c.y - ring, width: 2 * ring, height: 2 * ring))
            coin(ctx, c, 24 + 1.5 * pulse, skull: true)
            return
        }
        if scanning {                                 // radar sweep, no needle while tracking is stale
            let a = now * 3.4
            ctx.setStrokeColor(rgb(150, 190, 255, 0.85))
            ctx.setLineWidth(2.5)
            ctx.setLineCap(.round)
            ctx.strokeLineSegments(between: [c, CGPoint(x: c.x + CGFloat(sin(a)) * 31, y: c.y - CGFloat(cos(a)) * 31)])
            ctx.setFillColor(rgb(150, 190, 255, 0.9))
            ctx.fillEllipse(in: CGRect(x: c.x - 3.5, y: c.y - 3.5, width: 7, height: 7))
            return
        }
        // One straight arrow, always solid, drawn as a 3D block lying on a tilted ground plane (like a car sat-nav):
        // lit top face, darker side walls, soft shadow. It turns about the vertical axis: away from the viewer is
        // where the player faces, and it points the way to turn. There is no up/down: the map has no heights.
        // Closeness changes its shape and its glow: long and skinny at 60 m or more, short, stubby and thick
        // right at the chest, with a halo that grows and heats up from gold to hot orange.
        let onCourse = abs(angle) < 15
        let k = near * near * (3 - 2 * near)                  // smoothstep, so the shape change is spread over the approach
        func mix(_ far: Double, _ close: Double) -> Double { far + (close - far) * k }
        let tip = mix(36, 27), tail = mix(-33, -23), shaft = mix(3.8, 12.5), wing = mix(12, 26), neck = tip - mix(20, 25)
        let thick = mix(8, 14)
        let tilt = 50.0 * .pi / 180, eye = 190.0, a = angle * .pi / 180, ground = CGPoint(x: c.x, y: c.y + 5)
        /// Ground-plane point (x right, y forward of the arrow, z up) to the screen.
        func project(_ x: Double, _ y: Double, _ z: Double) -> CGPoint {
            let rx = x * cos(a) + y * sin(a), ry = -x * sin(a) + y * cos(a)
            let scale = eye / (eye + ry * sin(tilt) - z * cos(tilt))
            return CGPoint(x: ground.x + CGFloat(rx * scale), y: ground.y - CGFloat((ry * cos(tilt) + z * sin(tilt)) * scale))
        }
        ctx.saveGState()
        ctx.addEllipse(in: CGRect(x: c.x - r + 6, y: c.y - r + 6, width: 2 * r - 12, height: 2 * r - 12))
        ctx.clip()
        if near > 0.05 {                                      // the dial face warms up behind the arrow
            ctx.setFillColor(heatColor(near, 0.2 * near, shade: 0.8))
            ctx.fill(CGRect(x: c.x - r, y: c.y - r, width: 2 * r, height: 2 * r))
        }
        ctx.setStrokeColor(rgb(255, 255, 255, 0.13))          // the ground: rings lying flat on the tilted plane
        ctx.setLineWidth(1.3)
        for radius in [16.0, 31.0, 46.0, 61.0] {
            let rings = CGMutablePath()
            rings.addLines(between: (0...40).map { i -> CGPoint in
                let t = Double(i) / 40 * 2 * .pi, x = radius * cos(t), y = radius * sin(t), scale = eye / (eye + y * sin(tilt))
                return CGPoint(x: ground.x + CGFloat(x * scale), y: ground.y - CGFloat(y * cos(tilt) * scale))
            })
            ctx.addPath(rings)
            ctx.strokePath()
        }
        ctx.restoreGState()

        let plan: [(Double, Double)] = [(0, tip), (wing, neck), (shaft, neck), (shaft, tail), (-shaft, tail), (-shaft, neck), (-wing, neck)]
        func polygon(_ points: [CGPoint]) -> CGPath {
            let path = CGMutablePath()
            path.addLines(between: points)
            path.closeSubpath()
            return path
        }
        let top = polygon(plan.map { project($0.0, $0.1, thick) })
        // Side walls that face the viewer, farthest first. `light` is brighter for walls turned to the left.
        var walls: [(depth: Double, light: Double, path: CGPath)] = []
        for i in 0..<plan.count {
            let p = plan[i], q = plan[(i + 1) % plan.count]
            let dx = q.0 - p.0, dy = q.1 - p.1, length = max(hypot(dx, dy), 0.001)
            let nx = (dy * cos(a) + dx * sin(a)) / length, ny = (-dy * sin(a) - dx * cos(a)) / length   // outward normal, turned
            if ny >= 0 { continue }
            let depth = (-(p.0 + q.0) * sin(a) + (p.1 + q.1) * cos(a)) / 2
            walls.append((depth, 0.46 - 0.16 * nx, polygon([project(p.0, p.1, thick), project(q.0, q.1, thick), project(q.0, q.1, 0), project(p.0, p.1, 0)])))
        }
        walls.sort { $0.depth > $1.depth }
        let body = CGMutablePath()
        body.addPath(top)
        for wall in walls { body.addPath(wall.path) }
        ctx.saveGState()
        ctx.setLineJoin(.round)
        ctx.saveGState()                                      // soft shadow on the ground
        ctx.translateBy(x: 3, y: 4)
        ctx.setShadow(offset: .zero, blur: 4 * unit, color: rgb(0, 0, 0, 0.6))
        ctx.addPath(polygon(plan.map { project($0.0, $0.1, 0) }))
        ctx.setFillColor(rgb(0, 0, 0, 0.45))
        ctx.fillPath()
        ctx.restoreGState()
        for pass in 0..<(near > 0.5 ? 2 : 1) {                // the glow: wider, hotter and doubled up close
            ctx.saveGState()
            let blur = pass == 0 ? 6 + 20 * near * (0.7 + 0.3 * throb) : 5
            ctx.setShadow(offset: .zero, blur: CGFloat(blur) * unit,
                          color: near > 0.05 ? heatColor(near, 0.75 + 0.25 * near, flash: pass == 0 ? 0 : 0.6)
                              : onCourse ? rgb(255, 240, 150, 0.95) : rgb(255, 170, 30, 0.7))
            ctx.addPath(body)
            ctx.setFillColor(ink)
            ctx.setStrokeColor(ink)
            ctx.setLineWidth(3.6)
            ctx.drawPath(using: .fillStroke)
            ctx.restoreGState()
        }
        for wall in walls {                                   // walls: deep gold far away, hot orange up close
            ctx.addPath(wall.path)
            ctx.setFillColor(heatColor(max(near, 0.3), shade: wall.light * (0.8 + 0.2 * near)))
            ctx.fillPath()
            ctx.addPath(wall.path)
            ctx.setStrokeColor(rgb(22, 12, 4, 0.55))
            ctx.setLineWidth(0.8)
            ctx.strokePath()
        }
        let lift = max(near, onCourse ? 0.6 : 0)              // top face: brighter when on course and when close
        ctx.addPath(top)
        ctx.setFillColor(rgb(255, 230 + 20 * lift, 120 + 94 * lift))
        ctx.fillPath()
        ctx.addPath(polygon([(0, tip), (wing, neck), (shaft, neck), (shaft, tail), (0, tail)].map { project($0.0, $0.1, thick) }))
        ctx.setFillColor(rgb(250 + 5 * lift, 190 + 40 * lift, 52 + 80 * lift))
        ctx.fillPath()
        if near > 0.3 {
            ctx.addPath(top)
            ctx.setFillColor(rgb(255, 255, 255, 0.45 * (near - 0.3) / 0.7 * throb))
            ctx.fillPath()
        }
        ctx.addPath(top)
        ctx.setStrokeColor(rgb(255, 252, 230, 0.9))           // bright rim on the top face's edge
        ctx.setLineWidth(0.9)
        ctx.strokePath()
        ctx.restoreGState()
    }

    /// A token under the game's compass strip at the chest's bearing. It never covers the strip itself.
    func compassPin(_ ctx: CGContext, _ s: Snapshot, alpha: Double) {
        let cal = s.compass ?? [958.5, 58, 3.5625]
        let limit = 80.0
        let off = clamp(pinAngle, -limit, limit)
        let x = CGFloat((cal[0] + off * cal[2]) / 1.5), top = CGFloat(cal[1] / 1.5)
        let outside = abs(pinAngle) > limit
        ctx.saveGState()
        if outside { ctx.setAlpha(CGFloat(alpha * 0.8)) }
        ctx.setFillColor(gold)
        ctx.setStrokeColor(ink)
        ctx.setLineWidth(1.4)
        ctx.setLineJoin(.round)
        if outside {
            let d: CGFloat = pinAngle > 0 ? 1 : -1
            ctx.move(to: CGPoint(x: x + d * 17, y: top + 13))
            ctx.addLine(to: CGPoint(x: x + d * 10, y: top + 8))
            ctx.addLine(to: CGPoint(x: x + d * 10, y: top + 18))
        } else {
            ctx.move(to: CGPoint(x: x, y: top))
            ctx.addLine(to: CGPoint(x: x - 5, y: top + 7))
            ctx.addLine(to: CGPoint(x: x + 5, y: top + 7))
        }
        ctx.closePath()
        ctx.drawPath(using: .fillStroke)
        coin(ctx, CGPoint(x: x, y: top + 13), 8, skull: false)
        ctx.restoreGState()
    }

    /// The route to the chest and the chest on the game's minimap (north-up, player in the middle).
    /// `drawn` under 1 shows only that share of the line from the player out: a new route draws itself on.
    func minimap(_ ctx: CGContext, _ s: Snapshot, drawn: Double = 1) {
        let cal = (s.mini ?? [1760, 157, 1.3791, 1638, 36, 1886, 276]).map { $0 / 1.5 }
        guard cal.count == 7, let target = s.target, target.count == 2 else { return }
        let scale = cal[2]
        func place(_ p: [Double]) -> CGPoint {
            CGPoint(x: cal[0] + (p[0] - px) * scale, y: cal[1] + (p[1] - py) * scale)
        }
        let box = CGRect(x: cal[3], y: cal[4], width: cal[5] - cal[3], height: cal[6] - cal[4])
        let me = CGPoint(x: cal[0], y: cal[1])
        ctx.saveGState()
        ctx.clip(to: box)
        var points = ((s.path ?? []).filter { $0.count == 2 }.map(place) + [place(target)]).filter { hypot($0.x - me.x, $0.y - me.y) > 9 }
        if points.count > 0 {
            let first = points[0]
            let d = hypot(first.x - me.x, first.y - me.y)
            let start = CGPoint(x: me.x + (first.x - me.x) * 9 / d, y: me.y + (first.y - me.y) * 9 / d)
            if drawn < 1 {                            // cut the line at `drawn` of its length
                let all = [start] + points
                var left = zip(all, all.dropFirst()).reduce(0.0) { $0 + Double(hypot($1.1.x - $1.0.x, $1.1.y - $1.0.y)) } * max(drawn, 0)
                points = []
                for (p, q) in zip(all, all.dropFirst()) {
                    let length = Double(hypot(q.x - p.x, q.y - p.y))
                    if length <= left { points.append(q); left -= length; continue }
                    let k = CGFloat(left / max(length, 0.001))
                    points.append(CGPoint(x: p.x + (q.x - p.x) * k, y: p.y + (q.y - p.y) * k))
                    break
                }
            }
            for (color, width) in [(rgb(30, 14, 0, 0.85), CGFloat(5)), (goldHi, CGFloat(2.6))] {
                ctx.setStrokeColor(color)
                ctx.setLineWidth(width)
                ctx.setLineCap(.round)
                ctx.setLineJoin(.round)
                ctx.addLines(between: [start] + points)
                ctx.strokePath()
            }
        }
        ctx.restoreGState()
        var pin = place(target)
        let inner = box.insetBy(dx: 9, dy: 9)
        if !inner.contains(pin) {
            let dx = pin.x - me.x, dy = pin.y - me.y
            let k = min(dx == 0 ? 1e9 : (dx > 0 ? inner.maxX - me.x : me.x - inner.minX) / abs(dx),
                        dy == 0 ? 1e9 : (dy > 0 ? inner.maxY - me.y : me.y - inner.minY) / abs(dy))
            pin = CGPoint(x: me.x + dx * k, y: me.y + dy * k)
        }
        if drawn >= 0.95 { coin(ctx, pin, 7, skull: false) }
    }
}

// MARK: offline render

let arguments = CommandLine.arguments
if arguments.count == 4, arguments[1] == "--render", let width = Int(arguments[2]), let height = Int(arguments[3]) {
    let hud = Hud()
    let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4, space: space,
                        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
    var clock = 0.0
    while let line = readLine() {
        let snapshot = try? JSONDecoder().decode(Snapshot.self, from: Data(line.utf8))
        clock = snapshot?.t ?? clock + 1.0 / 30
        hud.feed(snapshot, at: clock)
        ctx.clear(CGRect(x: 0, y: 0, width: width, height: height))
        hud.draw(ctx, width: CGFloat(width), height: CGFloat(height), at: clock)
        FileHandle.standardOutput.write(Data(bytes: ctx.data!, count: width * height * 4))
    }
    exit(0)
}

// MARK: live panel

final class HudView: NSView {
    let hud = Hud()
    override func draw(_ dirtyRect: NSRect) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        hud.draw(ctx, width: bounds.width, height: bounds.height, at: CACurrentMediaTime())
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 720),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
panel.level = .floating
panel.ignoresMouseEvents = true
panel.hidesOnDeactivate = false
panel.isOpaque = false
panel.hasShadow = false
panel.backgroundColor = .clear
let view = HudView(frame: panel.contentView!.bounds)
view.autoresizingMask = [.width, .height]
panel.contentView?.addSubview(view)
var windowID: UInt32?
var gameRect: [Double]?

/// Keep the panel exactly over the gameplay picture inside the tracked window.
func place() -> Bool {
    guard let id = windowID,
          let info = CGWindowListCopyWindowInfo(.optionIncludingWindow, id) as? [[String: Any]],
          let window = info.first(where: { ($0[kCGWindowNumber as String] as? UInt32) == id }),
          (window[kCGWindowIsOnscreen as String] as? Bool) == true,
          let bounds = window[kCGWindowBounds as String] as? [String: CGFloat],
          let x = bounds["X"], let y = bounds["Y"], let w = bounds["Width"], let h = bounds["Height"],
          let desktopTop = NSScreen.screens.first?.frame.maxY else { return false }
    // Without a rectangle from the runner, assume 16:9 gameplay under a title bar.
    let fallback = min(h, w * 9 / 16)
    let game = gameRect.map { CGRect(x: x + $0[0] * w, y: y + $0[1] * h, width: $0[2] * w, height: $0[3] * h) }
        ?? CGRect(x: x, y: y + h - fallback, width: w, height: fallback)
    panel.setFrame(NSRect(x: game.minX, y: desktopTop - game.maxY, width: game.width, height: game.height), display: false)
    return true
}

func update(_ snapshot: Snapshot?) {
    let now = CACurrentMediaTime()
    if let id = snapshot?.window { windowID = id }
    if let rect = snapshot?.game, rect.count == 4 { gameRect = rect }
    view.hud.feed(snapshot, at: now)
    guard view.hud.visible(at: now), place() else {
        panel.orderOut(nil)
        return
    }
    if !panel.isVisible {
        panel.orderFrontRegardless()
        FileHandle.standardError.write(Data("Live waypoint HUD shown on gameplay.\n".utf8))
    }
}

// Redraw at display rate so the needle and the chest pop stay smooth between 20 Hz snapshots.
Timer.scheduledTimer(withTimeInterval: 1.0 / 60, repeats: true) { _ in
    guard panel.isVisible else { return }
    if view.hud.visible(at: CACurrentMediaTime()) { view.needsDisplay = true } else { panel.orderOut(nil) }
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
