// Native iOS 27 feasibility component ONLY. Not linked to the current Expo app.
// Compile against the final iOS 27 SDK and test on an actual device before enabling.
// No recording, audio, screen upload, provider access or App Store claim.
import Foundation
import CoreGraphics
import CoreImage
import CoreMedia
import CoreVideo
import ScreenCaptureKit
import UIKit

@available(iOS 27.0, *)
final class DropRateAuctionScreenProbe: NSObject,
    SCContentSharingPickerObserver, SCStreamOutput, SCStreamDelegate {

    struct CroppedFrame {
        let jpeg: Data
        let perceptualHash64: String
        let monotonicMs: Double
    }

    private let frameQueue = DispatchQueue(
        label: "uk.droprate.auctionlens.capture", qos: .userInitiated
    )
    private let context = CIContext(options: [.useSoftwareRenderer: false])
    private var stream: SCStream?
    private var lastSampleMs: Double = -Double.infinity
    // User-drawn item region in TOP-LEFT normalized screen coordinates.
    // A value MUST be supplied and confirmed before the picker appears.
    private var region: CGRect = .null

    var onFrame: ((CroppedFrame) -> Void)?
    var onStateChange: ((String) -> Void)?

    func presentPicker(region userConfirmedRegion: CGRect) {
        guard validRegion(userConfirmedRegion) else {
            onStateChange?("REGION_REQUIRED")
            return
        }
        region = userConfirmedRegion
        let picker = SCContentSharingPicker.shared
        var config = SCContentSharingPickerConfiguration()
        config.showsMicrophoneControl = false
        config.showsCameraControl = false
        picker.defaultConfiguration = config
        picker.add(self)
        // Only Apple's picker can authorize a shared screen source.
        picker.present()
        onStateChange?("AWAITING_SYSTEM_PERMISSION")
    }

    func stop() {
        SCContentSharingPicker.shared.remove(self)
        region = .null
        let existing = stream
        stream = nil
        onStateChange?("STOPPED")
        Task { try? await existing?.stopCapture() }
    }

    func contentSharingPicker(
        _ picker: SCContentSharingPicker,
        didUpdateWith filter: SCContentFilter,
        for existing: SCStream?
    ) {
        Task {
            if let current = stream { try? await current.stopCapture() }
            let config = SCStreamConfiguration()
            config.capturesAudio = false
            config.minimumFrameInterval = CMTime(value: 1, timescale: 4)
            config.pixelFormat = kCVPixelFormatType_32BGRA
            config.queueDepth = 3
            let newStream = SCStream(filter: filter, configuration: config, delegate: self)
            do {
                try newStream.addStreamOutput(self, type: .screen, sampleHandlerQueue: frameQueue)
                stream = newStream
                try await newStream.startCapture()
                onStateChange?("CAPTURING")
            } catch {
                stream = nil
                onStateChange?("CAPTURE_ERROR")
            }
        }
    }

    func contentSharingPicker(_ picker: SCContentSharingPicker,
                              didCancelFor stream: SCStream?) {
        stop()
    }

    func contentSharingPickerStartDidFailWithError(_ error: Error) {
        stop()
        onStateChange?("PERMISSION_UNAVAILABLE")
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        stop()
        onStateChange?("CAPTURE_REVOKED")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen, CMSampleBufferIsValid(sampleBuffer),
              let pixel = CMSampleBufferGetImageBuffer(sampleBuffer),
              validRegion(region) else { return }

        let nowMs = ProcessInfo.processInfo.systemUptime * 1000
        guard nowMs - lastSampleMs >= 250 else { return }
        lastSampleMs = nowMs

        let input = CIImage(cvPixelBuffer: pixel)
        let bounds = input.extent
        let rect = CGRect(
            x: bounds.minX + bounds.width * region.minX,
            y: bounds.minY + bounds.height * (1 - region.maxY),
            width: bounds.width * region.width,
            height: bounds.height * region.height
        ).integral.intersection(bounds)
        guard rect.width >= 200, rect.height >= 200 else { return }

        // Crop the product before producing bytes. Never forward the full screen.
        let cropped = input.cropped(to: rect)
        let scale = min(1.0, 480.0 / max(rect.width, rect.height))
        let image = cropped
            .transformed(by: CGAffineTransform(translationX: -rect.minX, y: -rect.minY))
            .transformed(by: CGAffineTransform(scaleX: scale, y: scale))
        guard let cg = context.createCGImage(image, from: image.extent),
              let jpeg = UIImage(cgImage: cg).jpegData(compressionQuality: 0.72),
              let hash = dhash(cg) else { return }
        // A protected or mostly-black region cannot be recognized.
        guard hash.hasVisibleContrast else {
            onStateChange?("CAPTURE_BLOCKED")
            return
        }
        // On-device consumer decides which stable crops to send to FastAPI.
        // This proof deliberately does not perform any network request.
        onFrame?(CroppedFrame(jpeg: jpeg, perceptualHash64: hash.hex,
                              monotonicMs: nowMs))
    }

    private func validRegion(_ value: CGRect) -> Bool {
        return !value.isNull && value.width >= 0.10 && value.height >= 0.10
            && value.minX >= 0 && value.minY >= 0
            && value.maxX <= 1 && value.maxY <= 1
    }

    private struct HashData {
        let hex: String
        let hasVisibleContrast: Bool
    }

    private func dhash(_ cg: CGImage) -> HashData? {
        var samples = [UInt8](repeating: 0, count: 9 * 8)
        let drawn = samples.withUnsafeMutableBytes { pixels -> Bool in
            guard let context = CGContext(
                data: pixels.baseAddress, width: 9, height: 8,
                bitsPerComponent: 8, bytesPerRow: 9,
                space: CGColorSpaceCreateDeviceGray(),
                bitmapInfo: CGImageAlphaInfo.none.rawValue
            ) else { return false }
            context.draw(cg, in: CGRect(x: 0, y: 0, width: 9, height: 8))
            return true
        }
        guard drawn else { return nil }
        var bits: UInt64 = 0
        for y in 0..<8 {
            for x in 0..<8 {
                bits <<= 1
                if samples[y * 9 + x] > samples[y * 9 + x + 1] {
                    bits |= 1
                }
            }
        }
        let minimum = samples.min() ?? 0
        let maximum = samples.max() ?? 0
        return HashData(hex: String(format: "%016llx", bits),
                        hasVisibleContrast: Int(maximum) - Int(minimum) >= 12)
    }
}
