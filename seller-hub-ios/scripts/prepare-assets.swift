// Build-time fitting of the existing Drop Rate logo, without redesigning it.
import AppKit
import Foundation

let source = URL(fileURLWithPath: "../backend/app/static/brand-assets/drop-rate-logo.png")
guard let logo = NSImage(contentsOf: source),
      let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1024, pixelsHigh: 1024,
          bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
          colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
      let context = NSGraphicsContext(bitmapImageRep: bitmap) else { fatalError("The existing logo is missing") }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context
NSColor.white.setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1024, height: 1024)).fill()
let height = 960 * logo.size.height / logo.size.width
logo.draw(in: NSRect(x: 32, y: (1024 - height) / 2, width: 960, height: height))
NSGraphicsContext.restoreGraphicsState()
guard let data = bitmap.representation(using: .png, properties: [:]) else { fatalError("Cannot prepare app icon") }
try data.write(to: URL(fileURLWithPath: "Assets.xcassets/AppIcon.appiconset/icon.png"))
