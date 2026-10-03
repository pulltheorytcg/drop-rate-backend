// Build-time fitting of the existing Drop Rate logo, without redesigning it.
import Foundation
import CoreGraphics
import ImageIO

let source = URL(fileURLWithPath: "../backend/app/static/brand-assets/drop-rate-logo.png")
guard let input = CGImageSourceCreateWithURL(source as CFURL, nil),
      let logo = CGImageSourceCreateImageAtIndex(input, 0, nil) else {
    fatalError("Cannot read the existing Drop Rate logo")
}
guard let context = CGContext(data: nil, width: 1024, height: 1024, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
    fatalError("Cannot create app icon canvas")
}
context.setFillColor(CGColor(gray: 1, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
context.interpolationQuality = .high
let height = 960.0 * Double(logo.height) / Double(logo.width)
context.draw(logo, in: CGRect(x: 32, y: (1024 - height) / 2, width: 960, height: height))
let output = URL(fileURLWithPath: "Assets.xcassets/AppIcon.appiconset/icon.png")
guard let image = context.makeImage(),
      let destination = CGImageDestinationCreateWithURL(output as CFURL, "public.png" as CFString, 1, nil) else {
    fatalError("Cannot prepare app icon output")
}
CGImageDestinationAddImage(destination, image, nil)
guard CGImageDestinationFinalize(destination) else { fatalError("Cannot save app icon") }
