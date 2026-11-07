package com.pulltheory.tcg;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.ActivityNotFoundException;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.*;
import android.view.*;
import android.widget.*;

public final class MainActivity extends Activity {
    private static final String ENTRY = "https://app.droprate.co.uk/app";
    private WebView web;
    private LinearLayout root;
    private TextView error;
    private Button retry;
    private PermissionRequest cameraRequest;
    private ValueCallback<Uri[]> files;

    private static boolean https(Uri uri) {
        return uri != null && "https".equalsIgnoreCase(uri.getScheme()) && uri.getUserInfo() == null;
    }
    private static boolean trusted(Uri uri) {
        return https(uri) && "app.droprate.co.uk".equalsIgnoreCase(uri.getHost()) && (uri.getPort() == -1 || uri.getPort() == 443);
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xff071b3f);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            if (android.os.Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets padding = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                v.setPadding(padding.left, padding.top, padding.right, padding.bottom);
            } else { v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom()); }
            return insets;
        });
        error = new TextView(this);
        error.setTextColor(0xffffffff);
        error.setPadding(24,24,24,24);
        retry = new Button(this);
        retry.setText("Try again");
        retry.setOnClickListener(v -> {
            error.setVisibility(View.GONE); retry.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
            if (trusted(Uri.parse(web.getUrl() == null ? "" : web.getUrl()))) web.reload(); else web.loadUrl(ENTRY);
        });
        root.addView(error); root.addView(retry);
        error.setVisibility(View.GONE); retry.setVisibility(View.GONE);
        web = new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(true); // Android's selected photo URIs.
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.getSettings().setSupportMultipleWindows(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(false);
        root.addView(web, new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (trusted(request.getUrl())) return false;
                if (request.isForMainFrame()) external(request.getUrl());
                return true;
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError failure) {
                if (req.isForMainFrame()) showError("Unable to open Drop Rate. Check your connection and try again.");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest req, WebResourceResponse response) {
                if (req.isForMainFrame() && response.getStatusCode() >= 400) showError("Drop Rate is temporarily unavailable. Please try again.");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    if (!trusted(request.getOrigin()) || !java.util.Arrays.asList(request.getResources()).contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) { request.deny(); return; }
                    if (cameraRequest != null) cameraRequest.deny();
                    cameraRequest = request;
                    if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) finishCamera(true);
                    else requestPermissions(new String[]{Manifest.permission.CAMERA}, 10);
                });
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) { if (cameraRequest == request) cameraRequest = null; }
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!trusted(Uri.parse(view.getUrl() == null ? "" : view.getUrl()))) { callback.onReceiveValue(null); return true; }
                if (files != null) files.onReceiveValue(null);
                files = callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("image/*");
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(pick, 11); }
                catch (ActivityNotFoundException e) { files.onReceiveValue(null); files = null; }
                return true;
            }
            @Override public boolean onCreateWindow(WebView view, boolean dialog, boolean gesture, android.os.Message result) {
                if (!gesture) return false;
                WebView popup = new WebView(MainActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                        Uri url = request.getUrl();
                        if (trusted(url)) web.loadUrl(url.toString()); else external(url);
                        popup.destroy();
                        return true;
                    }
                });
                ((WebView.WebViewTransport) result.obj).setWebView(popup); result.sendToTarget();
                return true;
            }
        });
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, () -> { if (web.canGoBack()) web.goBack(); else finish(); });
        }
        web.loadUrl(ENTRY);
    }
    private void finishCamera(boolean allowed) {
        if (cameraRequest == null) return;
        if (allowed && trusted(Uri.parse(web.getUrl() == null ? "" : web.getUrl()))) cameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE}); else cameraRequest.deny();
        cameraRequest = null;
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == 10) finishCamera(results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 11 && files != null) {
            files.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data)); files = null;
        }
    }
    private void external(Uri uri) {
        if (!https(uri)) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (ActivityNotFoundException e) { Toast.makeText(this,"No browser is available to open this link.",Toast.LENGTH_LONG).show(); }
    }
    private void showError(String text) {
        web.setVisibility(View.GONE); error.setText(text); error.setVisibility(View.VISIBLE); retry.setVisibility(View.VISIBLE);
    }
    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onPause() { web.onPause(); CookieManager.getInstance().flush(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) web.onResume(); }
    @Override protected void onDestroy() {
        if (files != null) files.onReceiveValue(null);
        if (cameraRequest != null) cameraRequest.deny();
        root.removeView(web); web.destroy(); super.onDestroy();
    }
}
