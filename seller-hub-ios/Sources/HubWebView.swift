import SwiftUI
import WebKit
import SafariServices

struct HubWebView: UIViewRepresentable {
    @ObservedObject var state: HubState
    func makeCoordinator() -> Coordinator { Coordinator(state: state) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = .clear
        // The hub owns navigation and unsaved forms; do not add a second toolbar
        // or swipe-to-reload that could discard a scan or duplicate a submission.
        web.allowsBackForwardNavigationGestures = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        context.coordinator.attach(web)
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.stopLoading()
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "hubSession")
        uiView.navigationDelegate = nil
        uiView.uiDelegate = nil
        coordinator.state.retry = nil
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
        let state: HubState
        private weak var web: WKWebView?
        private let store = SessionStore()
        private var session: String?
        private var script = ""
        private var downloads: [ObjectIdentifier: URL] = [:]
        private var initialized = false
        private var pendingPersistence = false

        init(state: HubState) { self.state = state }

        func attach(_ web: WKWebView) {
            self.web = web
            web.navigationDelegate = self
            web.uiDelegate = self
            web.configuration.userContentController.add(WeakMessageHandler(self), name: "hubSession")
            state.retry = { [weak self] in self?.retry() }
            retry()
        }

        private func retry() {
            guard let web else { return }
            state.error = nil
            state.loading = true
            if pendingPersistence {
                do {
                    if let session { try store.save(session) } else { try store.clear() }
                    pendingPersistence = false
                } catch {
                    state.loading = false
                    state.error = "Unlock your iPhone, then retry to finish saving your sign-in change."
                    return
                }
            }
            if !initialized {
                do {
                    // A locked/unavailable Keychain must not silently boot a
                    // different account and overwrite the previous session.
                    session = try store.read()
                    guard let resource = Bundle.main.url(forResource: "session-bridge", withExtension: "js") else {
                        throw SessionStore.StoreError.unavailable
                    }
                    script = try String(contentsOf: resource, encoding: .utf8)
                    updateBootstrap()
                    initialized = true
                } catch {
                    state.loading = false
                    state.error = "Unlock your iPhone and try again. Your saved sign-in could not be opened."
                    return
                }
            }
            if HubPolicy.isHub(web.url) { web.reload() }
            else { web.load(URLRequest(url: HubPolicy.entry)) }
        }

        private func updateBootstrap() {
            guard let content = web?.configuration.userContentController else { return }
            let source = script.replacingOccurrences(of: "__DROP_RATE_BOOTSTRAP__", with: session ?? "null")
            content.removeAllUserScripts()
            content.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.frameInfo.isMainFrame,
                  HubPolicy.isHub(message.frameInfo.request.url),
                  message.frameInfo.securityOrigin.protocol == "https",
                  message.frameInfo.securityOrigin.host == HubPolicy.host,
                  let body = message.body as? [String: Any], body["type"] as? String == "session" else { return }
            do {
                if body["value"] is NSNull {
                    session = nil
                } else if let raw = body["value"] as? String, let clean = HubPolicy.session(raw) {
                    session = clean
                } else { return }
                updateBootstrap()
                pendingPersistence = true
                if let session { try store.save(session) } else { try store.clear() }
                pendingPersistence = false
            } catch {
                // Stop navigation on a failed logout write so a later launch
                // cannot silently resurrect a session the user tried to clear.
                web?.stopLoading()
                state.error = "Your sign-in could not be saved securely. Unlock your iPhone and try again."
            }
        }

        private var presenter: UIViewController? {
            var view = web?.window?.rootViewController
            while let next = view?.presentedViewController { view = next }
            return view
        }

        private func openExternal(_ url: URL) {
            guard HubPolicy.isExternalHTTPS(url), let presenter else { return }
            presenter.present(SFSafariViewController(url: url), animated: true)
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard !pendingPersistence else { decisionHandler(.cancel); return }
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if navigationAction.shouldPerformDownload && (HubPolicy.isHub(url) || HubPolicy.isHubBlob(url)) {
                decisionHandler(.download)
            } else if HubPolicy.isHub(url) {
                if navigationAction.targetFrame == nil {
                    webView.load(navigationAction.request)
                    decisionHandler(.cancel)
                } else { decisionHandler(.allow) }
            } else {
                // Credentials/session scripts never enter a third-party page.
                decisionHandler(.cancel)
                if navigationAction.targetFrame?.isMainFrame != false { openExternal(url) }
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard !pendingPersistence, let url = navigationAction.request.url else { return nil }
            if HubPolicy.isHub(url) { webView.load(navigationAction.request) }
            else { openExternal(url) }
            return nil
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            if navigationResponse.isForMainFrame, let response = navigationResponse.response as? HTTPURLResponse,
               response.statusCode >= 400 {
                state.loading = false
                state.error = "The Seller Hub is temporarily unavailable. Please try again."
                decisionHandler(.cancel)
            } else if !navigationResponse.canShowMIMEType {
                decisionHandler(.download)
            } else { decisionHandler(.allow) }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            state.loading = false
            state.error = nil
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            failed(error)
        }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
        private func failed(_ error: Error) {
            guard (error as NSError).code != NSURLErrorCancelled else { return }
            state.loading = false
            state.error = "Check your connection, then try again. Your account remains signed in."
        }
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            state.loading = false
            state.error = "iOS paused the Seller Hub. Reload to continue. Unsaved entries may need to be re-entered; check Inventory before saving again."
        }

        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            let trusted = origin.protocol == "https" && origin.host == HubPolicy.host
                && frame.isMainFrame && HubPolicy.isHub(frame.request.url)
            decisionHandler(trusted && type == .camera ? .prompt : .deny)
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            guard HubPolicy.isHub(frame.request.url), let presenter else { completionHandler(); return }
            let alert = UIAlertController(title: "Drop Rate", message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            presenter.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
            guard HubPolicy.isHub(frame.request.url), let presenter else { completionHandler(false); return }
            let alert = UIAlertController(title: "Drop Rate", message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
            alert.addAction(UIAlertAction(title: "Continue", style: .default) { _ in completionHandler(true) })
            presenter.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                     defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping (String?) -> Void) {
            guard HubPolicy.isHub(frame.request.url), let presenter else { completionHandler(nil); return }
            let alert = UIAlertController(title: "Drop Rate", message: prompt, preferredStyle: .alert)
            alert.addTextField { $0.text = defaultText }
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
            alert.addAction(UIAlertAction(title: "Continue", style: .default) { [weak alert] _ in
                completionHandler(alert?.textFields?.first?.text)
            })
            presenter.present(alert, animated: true)
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            download.delegate = self
        }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            download.delegate = self
        }
        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                      suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
            guard let url = response.url, HubPolicy.isHub(url) || HubPolicy.isHubBlob(url) else {
                completionHandler(nil); return
            }
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                let file = directory.appendingPathComponent(HubPolicy.downloadName(suggestedFilename))
                downloads[ObjectIdentifier(download)] = file
                completionHandler(file)
            } catch { completionHandler(nil); state.notice = "This file could not be downloaded. Please try again." }
        }
        func downloadDidFinish(_ download: WKDownload) {
            guard let file = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
            guard let presenter else { try? FileManager.default.removeItem(at: file.deletingLastPathComponent()); return }
            let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
            share.completionWithItemsHandler = { _, _, _, _ in
                try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
            }
            share.popoverPresentationController?.sourceView = web
            presenter.present(share, animated: true)
        }
        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            if let file = downloads.removeValue(forKey: ObjectIdentifier(download)) {
                try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
            }
            state.notice = "The download was interrupted. Please try again."
        }
    }
}

@MainActor
private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(userContentController, didReceive: message)
    }
}
