import UIKit
import WebKit

final class HubViewController: UIViewController, WKNavigationDelegate, WKUIDelegate {
    private var web: WKWebView!
    private let spinner = UIActivityIndicatorView(style: .large)
    private let recovery = UIStackView()
    private let message = UILabel()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 7/255, green: 27/255, blue: 63/255, alpha: 1)
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(web)
        NSLayoutConstraint.activate([
            web.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            web.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
            web.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        spinner.color = .systemTeal
        spinner.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(spinner)
        NSLayoutConstraint.activate([spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor), spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor)])
        recovery.axis = .vertical
        recovery.spacing = 20
        recovery.alignment = .center
        recovery.translatesAutoresizingMaskIntoConstraints = false
        message.textColor = .white
        message.numberOfLines = 0
        message.textAlignment = .center
        recovery.addArrangedSubview(message)
        let retry = UIButton(type: .system)
        retry.setTitle("Try again", for: .normal)
        retry.addTarget(self, action: #selector(retryLoad), for: .touchUpInside)
        recovery.addArrangedSubview(retry)
        view.addSubview(recovery)
        NSLayoutConstraint.activate([
            recovery.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            recovery.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24),
            recovery.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24)
        ])
        retryLoad()
    }
    override var preferredStatusBarStyle: UIStatusBarStyle { .lightContent }
    @objc private func retryLoad() {
        recovery.isHidden = true
        web.isHidden = false
        spinner.startAnimating()
        // Reload the same web view so a transient failure does not discard its session.
        if let url = web.url, NavigationPolicy.destination(url) == .hub { web.reload() }
        else { web.load(URLRequest(url: NavigationPolicy.entry)) }
    }
    private func fail(_ text: String) {
        spinner.stopAnimating()
        web.isHidden = true
        message.text = text
        recovery.isHidden = false
    }
    private func openBrowser(_ url: URL) {
        guard NavigationPolicy.destination(url) == .browser else { return }
        UIApplication.shared.open(url)
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        switch NavigationPolicy.destination(url) {
        case .hub: decisionHandler(.allow)
        case .browser:
            if navigationAction.targetFrame?.isMainFrame != false { openBrowser(url) }
            decisionHandler(.cancel)
        case .blocked: decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url else { return nil }
        if NavigationPolicy.destination(url) == .hub { webView.load(navigationAction.request) }
        else { openBrowser(url) }
        return nil
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) { spinner.startAnimating() }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { spinner.stopAnimating() }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { handle(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { handle(error) }
    private func handle(_ error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { fail("Unable to open Drop Rate. Check your connection and try again.") }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { fail("Drop Rate needs to reload. Tap Try again to continue.") }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if navigationResponse.isForMainFrame, let response = navigationResponse.response as? HTTPURLResponse, response.statusCode >= 400 {
            fail("Drop Rate is temporarily unavailable. Please try again.")
            decisionHandler(.cancel)
        } else { decisionHandler(.allow) }
    }
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        let trusted = origin.protocol == "https" && origin.host == "app.droprate.co.uk" && (origin.port == 0 || origin.port == 443)
        decisionHandler(trusted && frame.isMainFrame && type == .camera ? .prompt : .deny)
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = UIAlertController(title: "Drop Rate", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = UIAlertController(title: "Drop Rate", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        present(alert, animated: true)
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let alert = UIAlertController(title: "Drop Rate", message: prompt, preferredStyle: .alert)
        alert.addTextField { $0.text = defaultText }
        alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(alert.textFields?.first?.text) })
        present(alert, animated: true)
    }
}
