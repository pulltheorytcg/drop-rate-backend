import SwiftUI
import AVFoundation
import Vision

final class Camera: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "DropRate.Camera")
    private let output = AVCapturePhotoOutput()
    private var device: AVCaptureDevice?
    private var configured = false
    private var wantsCamera = false
    private var completion: ((Data) -> Void)?
    @Published var message: String?
    @Published var ready = false
    @Published var capturing = false
    @Published var torch = false

    func start() {
        queue.async { self.wantsCamera = true }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: configureAndStart()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
                if allowed { self?.configureAndStart() }
                else { self?.fail("Allow camera access in Settings to scan your collection.") }
            }
        default: fail("Allow camera access in Settings to scan your collection.")
        }
    }
    private func configureAndStart() {
        queue.async { [weak self] in
            guard let self else { return }
            guard wantsCamera else { return }
            do {
                if !configured {
                    session.beginConfiguration()
                    defer { session.commitConfiguration() }
                    session.sessionPreset = .photo
                    guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                        fail("A rear camera is required. Use a physical iPhone to test scanning."); return
                    }
                    let input = try AVCaptureDeviceInput(device: camera)
                    guard session.canAddInput(input), session.canAddOutput(output) else {
                        fail("The camera is unavailable. Close other camera apps and try again."); return
                    }
                    session.addInput(input); session.addOutput(output); device = camera; configured = true
                }
                session.startRunning()
                DispatchQueue.main.async { self.ready = self.session.isRunning; self.message = nil }
            } catch { fail("The camera could not start. Please try again.") }
        }
    }
    func stop() {
        queue.async { [weak self] in
            guard let self else { return }
            wantsCamera = false
            if let device, device.hasTorch, (try? device.lockForConfiguration()) != nil {
                device.torchMode = .off; device.unlockForConfiguration()
            }
            session.stopRunning()
            DispatchQueue.main.async { self.ready = false; self.torch = false }
        }
    }
    func toggleTorch() {
        queue.async { [weak self] in
            guard let self, let device, device.hasTorch else { return }
            do {
                try device.lockForConfiguration()
                device.torchMode = device.torchMode == .on ? .off : .on
                let on = device.torchMode == .on
                device.unlockForConfiguration()
                DispatchQueue.main.async { self.torch = on }
            } catch { fail("The torch is unavailable.") }
        }
    }
    func capture(completion: @escaping (Data) -> Void) {
        guard ready, !capturing else { return }
        capturing = true; self.completion = completion
        queue.async { [weak self] in
            guard let self else { return }
            let settings = AVCapturePhotoSettings()
            settings.flashMode = .off
            if let connection = output.connection(with: .video), connection.isVideoRotationAngleSupported(90) {
                connection.videoRotationAngle = 90
            }
            output.capturePhoto(with: settings, delegate: self)
        }
    }
    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard error == nil, let original = photo.fileDataRepresentation(), let image = UIImage(data: original) else {
            fail("The photo could not be captured. Please try again.")
            DispatchQueue.main.async { self.capturing = false }; return
        }
        // Render orientation into pixels and keep upload below the backend's image limit.
        let scale = min(1, 1600 / max(image.size.width, image.size.height))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let rendered = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        guard let data = rendered.jpegData(compressionQuality: 0.85) else {
            fail("Please retake this photo.")
            DispatchQueue.main.async { self.capturing = false }; return
        }
        DispatchQueue.main.async {
            self.capturing = false; self.completion?(data); self.completion = nil
        }
    }
    private func fail(_ text: String) { DispatchQueue.main.async { self.message = text } }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
        override func layoutSubviews() {
            super.layoutSubviews()
            if let connection = previewLayer.connection, connection.isVideoRotationAngleSupported(90) {
                connection.videoRotationAngle = 90
            }
        }
    }
    func makeUIView(context: Context) -> Preview {
        let view = Preview(); view.previewLayer.session = session; view.previewLayer.videoGravity = .resizeAspectFill; return view
    }
    func updateUIView(_ uiView: Preview, context: Context) {}
}

enum TextReader {
    static func read(_ data: Data) async throws -> LabelReading {
        try await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = false
            let supported = try request.supportedRecognitionLanguages()
            request.recognitionLanguages = ["en-US", "ja-JP"].filter { supported.contains($0) }
            let barcodes = VNDetectBarcodesRequest()
            try VNImageRequestHandler(data: data).perform([request, barcodes])
            let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
            let codes = (barcodes.results ?? []).compactMap(\.payloadStringValue).compactMap(LabelReading.certificateFromBarcode)
            return LabelReading.parse(lines: lines + codes)
        }.value
    }
}

struct ScannerView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var camera = Camera()
    @State private var mode: ScanMode = .raw
    @State private var capture: Capture?
    struct Capture: Identifiable { let id = UUID(); let data: Data; let mode: ScanMode }
    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(session: camera.session).ignoresSafeArea()
            VStack(spacing: 20) {
                HStack {
                    Button { dismiss() } label: { Image(systemName: "xmark").frame(width: 44, height: 44) }
                        .accessibilityLabel("Close scanner")
                    Spacer()
                    Text("DROP RATE").font(.headline).tracking(3)
                    Spacer()
                    Button { camera.toggleTorch() } label: {
                        Image(systemName: camera.torch ? "bolt.fill" : "bolt.slash.fill").frame(width: 44, height: 44)
                    }.accessibilityLabel("Toggle torch")
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(ScanMode.allCases) { item in
                            Button { mode = item } label: {
                                Text(item.rawValue).font(.subheadline.weight(.semibold)).padding(.horizontal, 16).padding(.vertical, 12)
                                    .background(mode == item ? DR.blue : .black.opacity(0.55), in: Capsule())
                            }.accessibilityAddTraits(mode == item ? .isSelected : [])
                        }
                    }
                }
                Spacer()
                RoundedRectangle(cornerRadius: 18).stroke(.white.opacity(0.85), lineWidth: 2)
                    .aspectRatio(mode.isComic ? 0.65 : mode.isGraded ? 0.58 : 0.72, contentMode: .fit)
                    .padding(.horizontal, 28).overlay(alignment: .top) {
                        Text(mode.isGraded ? "Include the entire label" : "Keep the whole front in view")
                            .font(.caption.weight(.medium)).padding(8).background(.black.opacity(0.6), in: Capsule()).offset(y: -16)
                    }.accessibilityHidden(true)
                Spacer()
                if let message = camera.message {
                    VStack {
                        Text(message).multilineTextAlignment(.center)
                        Button("Open Settings") { UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)!) }
                    }.padding().background(.black.opacity(0.8), in: RoundedRectangle(cornerRadius: 14))
                } else {
                    Text("English & Japanese · avoid glare").font(.subheadline).padding(10).background(.black.opacity(0.55), in: Capsule())
                }
                Button {
                    camera.capture { data in capture = Capture(data: data, mode: mode); camera.stop() }
                } label: {
                    Circle().fill(.white).frame(width: 68, height: 68).padding(6).overlay(Circle().stroke(.white, lineWidth: 3))
                }.disabled(!camera.ready || camera.capturing).opacity(camera.ready ? 1 : 0.4).accessibilityLabel("Scan \(mode.rawValue)")
                Text("Scan, check the match, then add").font(.caption).padding(.bottom, 12)
            }.padding(.horizontal, 16).foregroundStyle(.white)
        }
        .onAppear { camera.start() }.onDisappear { camera.stop() }
        .onChange(of: scenePhase) { _, phase in if phase == .active && capture == nil { camera.start() } else { camera.stop() } }
        .sheet(item: $capture, onDismiss: { camera.start() }) { captured in
            ScanReview(data: captured.data, mode: captured.mode)
        }
    }
}
