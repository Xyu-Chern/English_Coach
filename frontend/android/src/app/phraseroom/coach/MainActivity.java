package app.phraseroom.coach;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.Map;

public final class MainActivity extends Activity {
    private WebView web;
    private static final String ROOT = "http://localhost/";
    private static final Map<String,String> ASSETS = new java.util.HashMap<>();
    static {
        ASSETS.put("index.html", "text/html");
        ASSETS.put("style.css", "text/css");
        ASSETS.put("app.js", "text/javascript");
        ASSETS.put("cat.js", "text/javascript");
        ASSETS.put("blue-cat.svg", "image/svg+xml");
        ASSETS.put("workflow.js", "text/javascript");
        ASSETS.put("library.json", "application/json");
        ASSETS.put("manifest.webmanifest", "application/manifest+json");
        ASSETS.put("icon-192.png", "image/png");
        ASSETS.put("icon-512.png", "image/png");
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(52,80,109));
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (!local(u)) return null;
                String name = u.getPath().substring(1);
                if (name.isEmpty()) name = "index.html";
                String mime = ASSETS.get(name);
                if (mime != null) {
                    try {
                        return new WebResourceResponse(mime, mime.startsWith("image/") ? null : "UTF-8", getAssets().open(name));
                    } catch (IOException ignored) {}
                }
                return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", null, new ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri target = request.getUrl();
                if (local(target)) return false;
                if (!request.isForMainFrame() && "https".equals(target.getScheme())
                        && "phrase-room-coach.vercel.app".equals(target.getHost())
                        && "/api/search".equals(target.getPath())) return false;
                if (request.isForMainFrame() && ("https".equals(target.getScheme()) || "http".equals(target.getScheme()))) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, target)); }
                    catch (ActivityNotFoundException e) { Toast.makeText(MainActivity.this, target.toString(), Toast.LENGTH_LONG).show(); }
                }
                return true;
            }
        });
        setContentView(web);
        if (state == null || web.restoreState(state) == null) web.loadUrl(ROOT);
    }

    private static boolean local(Uri u) {
        return "http".equals(u.getScheme()) && "localhost".equals(u.getEncodedAuthority());
    }

    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); web.saveState(state); }
    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() { web.destroy(); super.onDestroy(); }
}
