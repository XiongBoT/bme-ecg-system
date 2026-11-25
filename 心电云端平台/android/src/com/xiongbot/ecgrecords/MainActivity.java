package com.xiongbot.ecgrecords;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.provider.DocumentsContract;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;
import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONTokener;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;

public final class MainActivity extends Activity {
    private WebView web;
    private LinearLayout root;
    private ReportPrinter reportPrinter;
    private UpdateReminder updateReminder;
    private CredentialStore credentials;
    private final Object credentialLock=new Object();
    private int credentialGeneration=0;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private String exportSession, exportUser, exportCookie;
    private static final int SAVE_CSV = 14;
    private static final int MAX_EXPORT_BYTES = 128 * 1024 * 1024;
    private static final AtomicBoolean cacheCleaned = new AtomicBoolean(false);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        reportPrinter=new ReportPrinter(this);
        updateReminder=new UpdateReminder(this);
        credentials=new CredentialStore(this);
        if(cacheCleaned.compareAndSet(false,true)) {
            File[] abandoned=getCacheDir().listFiles((dir,name)->name.startsWith("ecg-export-")&&name.endsWith(".csv"));
            if(abandoned!=null)for(File file:abandoned)file.delete();
        }
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.WHITE);
        // Android 15 enforces edge-to-edge. Keep controls clear of bars and keyboard.
        if (Build.VERSION.SDK_INT >= 30) root.setOnApplyWindowInsetsListener((v, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });
        else root.setFitsSystemWindows(true);
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(12), 0, dp(8), 0);
        TextView name = new TextView(this);
        name.setText("心电健康助手"); name.setTextSize(16); name.setTextColor(Color.rgb(8,127,113));
        toolbar.addView(name, new LinearLayout.LayoutParams(0, dp(48), 1));
        name.setGravity(Gravity.CENTER_VERTICAL);
        Button help = new Button(this); help.setText("说明");
        help.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("心电健康助手 " + appVersion())
            .setMessage("使用已有项目账号登录。查看记录和云端分析需要联网。\n\n账号与心电数据仅发送至项目服务器：\n" + WebPolicy.ORIGIN + "\n\n可自愿记住账号密码，使用 Android 系统密钥加密保存在本机；可在 APP 设置中清除。不自动保存心电文件。点击下载时可自行选择 CSV 保存位置。\n\n本应用用于课程研究。")
            .setNeutralButton("检查更新", (d,w) -> updateReminder.checkManually())
            .setPositiveButton("知道了", null).show());
        Button reload = new Button(this); reload.setText("重连");
        reload.setOnClickListener(v -> new AlertDialog.Builder(this).setTitle("重新连接？")
            .setMessage("将重新打开记录页，尚未保存的输入会清除。")
            .setNegativeButton("取消", null).setPositiveButton("重新连接", (d,w) -> web.loadUrl(WebPolicy.ORIGIN + "/")).show());
        toolbar.addView(help); toolbar.addView(reload); root.addView(toolbar);
        web = new WebView(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        WebView.setWebContentsDebuggingEnabled(false);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new Client());
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        web.loadUrl(WebPolicy.ORIGIN + "/");
        if (Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(0, this::goBack);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private void goBack() {
        // Fixed, trusted script; no interpolation of server data or native JS bridge.
        web.evaluateJavascript("(() => {const d=document.querySelector('dialog[open]');if(d){d.close();return true;}const b=document.getElementById('nav-records');const s=document.getElementById('workspace-shell');if(b&&s&&!s.hidden&&s.dataset.mobileView!=='records'){b.click();return true;}return false;})()", value -> {
            if ("true".equals(value)) return;
            if (web.canGoBack()) web.goBack(); else moveTaskToBack(true);
        });
    }
    @Override public void onBackPressed() { goBack(); }
    @Override protected void onPause() { if(updateReminder!=null)updateReminder.onPause(); web.onPause(); web.pauseTimers(); CookieManager.getInstance().flush(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) {web.onResume();web.resumeTimers();} if(updateReminder!=null)updateReminder.onResume(); }
    @Override public void onWindowFocusChanged(boolean focused) { super.onWindowFocusChanged(focused); if(updateReminder!=null)updateReminder.onWindowFocusChanged(focused); }
    @Override protected void onDestroy() { if(updateReminder!=null)updateReminder.close(); io.shutdownNow(); if(reportPrinter!=null)reportPrinter.close(); if(web != null) {web.stopLoading(); web.destroy();} super.onDestroy(); }

    private String appVersion(){
        try{return getPackageManager().getPackageInfo(getPackageName(),0).versionName;}
        catch(Exception ignored){return "";}
    }

    private void printReport(){
        final String cookie=CookieManager.getInstance().getCookie(WebPolicy.ORIGIN);
        // Only read an already-visible snapshot. No server text is interpolated into JS.
        web.evaluateJavascript("typeof UserExperience==='undefined'?null:UserExperience.printDocument()", encoded -> {
            if(isFinishing() || isDestroyed() || !WebPolicy.trusted(web.getUrl()) || cookie==null ||
                !cookie.equals(CookieManager.getInstance().getCookie(WebPolicy.ORIGIN)))return;
            try {
                Object result=new JSONTokener(encoded).nextValue();
                if(result instanceof String)reportPrinter.print((String)result);
                else Toast.makeText(this,"报告已失效，请重新打开预览",Toast.LENGTH_LONG).show();
            } catch(Exception ignored){Toast.makeText(this,"无法读取报告，请重试",Toast.LENGTH_LONG).show();}
        });
    }

    private boolean loginOrigin(){
        if(web==null||!WebPolicy.trusted(web.getUrl()))return false;
        String path=Uri.parse(web.getUrl()).getPath();return "/".equals(path)||"/index.html".equals(path);
    }
    private void credentialCommand(String action){
        if(!loginOrigin())return;
        final int generation; synchronized(credentialLock){generation=++credentialGeneration;}
        if("clear".equals(action)){
            io.execute(()->{try{synchronized(credentialLock){credentials.clear();}}catch(Exception ignored){runOnUiThread(()->Toast.makeText(this,"保存的登录信息未清除，请在应用设置中重试",Toast.LENGTH_LONG).show());}});return;
        }
        if("load".equals(action)){
            io.execute(()->{
                try{
                    final JSONObject saved; synchronized(credentialLock){if(generation!=credentialGeneration)return;saved=credentials.load();}
                    if(saved==null)return;
                    runOnUiThread(()->{synchronized(credentialLock){if(generation!=credentialGeneration||isDestroyed()||!loginOrigin())return;}
                        web.evaluateJavascript("if(typeof HealthAssistant!=='undefined')HealthAssistant.restoreLogin(JSON.parse("+JSONObject.quote(saved.toString())+"));",null);});
                }catch(Exception ignored){try{synchronized(credentialLock){if(generation==credentialGeneration)credentials.clear();}}catch(Exception unused){} }
            });return;
        }
        if(!"save".equals(action))return;
        final String cookie=CookieManager.getInstance().getCookie(WebPolicy.ORIGIN);
        if(cookie==null)return;
        // Fixed local script, no password in URL/history, no general-purpose native JS bridge.
        web.evaluateJavascript("typeof HealthAssistant==='undefined'?null:HealthAssistant.consumeCredentials()",encoded->{
            if(!loginOrigin()||!cookie.equals(CookieManager.getInstance().getCookie(WebPolicy.ORIGIN)))return;
            try{
                JSONObject value=new JSONObject(encoded);
                final String username=value.getString("username"),password=value.getString("password"),userId=value.getString("userId");
                io.execute(()->{
                    HttpsURLConnection connection=null;
                    try{
                        connection=(HttpsURLConnection)new URL(WebPolicy.ORIGIN+"/api/auth/me").openConnection();
                        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(10000);
                        connection.setRequestProperty("Cookie",cookie);connection.setRequestProperty("Cache-Control","no-store");
                        if(connection.getResponseCode()!=200)throw new Exception("Login changed");
                        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                        try(InputStream input=connection.getInputStream()){
                            byte[] buffer=new byte[1024];int count;
                            while((count=input.read(buffer))!=-1){if(bytes.size()+count>16384)throw new Exception("Unexpected response");bytes.write(buffer,0,count);}
                        }
                        JSONObject user=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8)).getJSONObject("user");
                        if(!userId.equals(user.getString("id"))||!username.equals(user.getString("username")))throw new Exception("Account mismatch");
                        synchronized(credentialLock){
                            if(generation!=credentialGeneration||!cookie.equals(CookieManager.getInstance().getCookie(WebPolicy.ORIGIN)))return;
                            credentials.save(username,password);
                        }
                        runOnUiThread(()->{if(!isFinishing()&&!isDestroyed())Toast.makeText(this,"账号密码已安全保存在此手机",Toast.LENGTH_SHORT).show();});
                    }catch(Exception ignored){runOnUiThread(()->{if(!isFinishing()&&!isDestroyed())Toast.makeText(this,"登录成功，但密码未保存，请稍后重试",Toast.LENGTH_LONG).show();});}
                    finally{if(connection!=null)connection.disconnect();}
                });
            }catch(Exception ignored){}
        });
    }

    private final class Client extends WebViewClient {
        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            String url = request.getUrl().toString();
            if (!WebPolicy.trusted(url)) return errorResponse(403, "Blocked", "仅允许连接项目服务器");
            String asset = WebPolicy.asset(request.getUrl().getPath());
            if (asset != null && "GET".equals(request.getMethod())) {
                try {
                    String mime = asset.endsWith(".css") ? "text/css" : asset.endsWith(".js") ? "application/javascript" : asset.endsWith(".png") ? "image/png" : "text/html";
                    return new WebResourceResponse(mime, asset.endsWith(".png") ? null : "UTF-8", 200, "OK",
                        Collections.singletonMap("Cache-Control", "no-store"), getAssets().open(asset));
                } catch (Exception ignored) { return errorResponse(404, "Not Found", "界面资源缺失，请重新安装应用"); }
            }
            // APIs use normal WebView networking, TLS, HttpOnly cookies and server CSRF.
            return null;
        }
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri uri = request.getUrl();
            if(request.isForMainFrame() && "ecg-credentials".equals(uri.getScheme())){
                if(loginOrigin() && uri.getQuery()==null && uri.getFragment()==null && (uri.getPath()==null || uri.getPath().isEmpty()))credentialCommand(uri.getHost());
                return true;
            }
            if (request.isForMainFrame() && "ecg-report".equals(uri.getScheme()) && "print".equals(uri.getHost())) {
                if (WebPolicy.trusted(view.getUrl()) && request.hasGesture()) printReport();
                return true;
            }
            if (request.isForMainFrame() && "ecg-export".equals(uri.getScheme()) && "download".equals(uri.getHost())) {
                if (WebPolicy.trusted(view.getUrl()) && request.hasGesture()) prepareExport(uri);
                else Toast.makeText(MainActivity.this,"请直接点击记录页的下载按钮",Toast.LENGTH_LONG).show();
                return true;
            }
            if (request.isForMainFrame() && WebPolicy.managementPage(uri.toString())) {
                try {startActivity(new Intent(Intent.ACTION_VIEW,uri));}
                catch(Exception e) {Toast.makeText(MainActivity.this,"请在系统浏览器打开项目网站的管理后台",Toast.LENGTH_LONG).show();}
                return true;
            }
            if (WebPolicy.trusted(uri.toString())) return false;
            Toast.makeText(MainActivity.this, "此链接不属于项目服务器", Toast.LENGTH_SHORT).show();
            return true;
        }
        @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
            handler.cancel();
            Toast.makeText(MainActivity.this, "服务器证书校验失败，请联系管理员后重连", Toast.LENGTH_LONG).show();
        }
        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) Toast.makeText(MainActivity.this, "暂时无法连接，请检查网络后点击重连", Toast.LENGTH_LONG).show();
        }
    }
    private WebResourceResponse errorResponse(int status, String reason, String message) {
        return new WebResourceResponse("text/plain", "UTF-8", status, reason,
            Collections.singletonMap("Cache-Control", "no-store"), new ByteArrayInputStream(message.getBytes(StandardCharsets.UTF_8)));
    }
    private void prepareExport(Uri uri) {
        String sid = uri.getLastPathSegment(), user = uri.getQueryParameter("user");
        if (!WebPolicy.sessionId(sid) || user == null || !user.matches("[a-f0-9]{32}")) return;
        exportSession=sid; exportUser=user; exportCookie=CookieManager.getInstance().getCookie(WebPolicy.ORIGIN);
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType("text/csv").putExtra(Intent.EXTRA_TITLE, sid + ".csv");
        try { startActivityForResult(intent, SAVE_CSV); }
        catch (Exception e) { clearExport(); Toast.makeText(this, "系统未提供文件保存器", Toast.LENGTH_LONG).show(); }
    }
    private void clearExport() { exportSession=null; exportUser=null; exportCookie=null; }
    private boolean discardDocument(Uri uri) {
        try {return DocumentsContract.deleteDocument(getContentResolver(),uri);}
        catch(Exception ignored) {return false;}
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request,result,data);
        if (request != SAVE_CSV) return;
        String sid=exportSession, user=exportUser, cookie=exportCookie; clearExport();
        if (result!=RESULT_OK || data==null || data.getData()==null) return;
        Uri destination=data.getData();
        if (sid==null || cookie==null || !cookie.equals(CookieManager.getInstance().getCookie(WebPolicy.ORIGIN))) {
            boolean removed=discardDocument(destination);
            Toast.makeText(this,"登录已改变，请重新下载"+(removed?"":"；请删除刚创建的空文件"),Toast.LENGTH_LONG).show();return;
        }
        AlertDialog progress=new AlertDialog.Builder(this).setTitle("正在下载 CSV").setMessage("正在校验账号并保存记录…").setCancelable(false).create();
        progress.show();
        io.execute(() -> {
            String outcome="已保存 CSV";
            boolean saved=false;
            HttpsURLConnection connection=null;
            File temporary=null;
            try {
                connection=(HttpsURLConnection)new URL(WebPolicy.ORIGIN+"/api/sessions/"+sid+"/export").openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(15000); connection.setReadTimeout(30000);
                connection.setRequestProperty("Cookie",cookie);
                connection.setRequestProperty("Cache-Control","no-store");
                connection.setRequestProperty("Accept-Encoding","identity");
                if (connection.getResponseCode()!=200 || !user.equals(connection.getHeaderField("X-ECG-User"))) throw new Exception("登录已失效或无权下载，请重新登录");
                String type=connection.getContentType();
                if (type==null || !type.startsWith("text/csv")) throw new Exception("服务器未返回 CSV，请稍后重试");
                if(connection.getContentLengthLong()>MAX_EXPORT_BYTES)throw new Exception("记录过大，请在电脑下载");
                temporary=File.createTempFile("ecg-export-",".csv",getCacheDir());
                try(InputStream input=connection.getInputStream(); OutputStream output=new FileOutputStream(temporary)) {
                    ExportCopy.copy(input,output,connection.getContentLengthLong(),MAX_EXPORT_BYTES);
                }
                if(!cookie.equals(CookieManager.getInstance().getCookie(WebPolicy.ORIGIN)))throw new Exception("登录已改变，请重新下载");
                try(InputStream input=new FileInputStream(temporary); OutputStream output=getContentResolver().openOutputStream(destination,"w")) {
                    if(output==null)throw new Exception("无法写入所选位置");
                    ExportCopy.copy(input,output,temporary.length(),MAX_EXPORT_BYTES);
                }
                saved=true;
            } catch (Exception e) {outcome="保存未完成："+e.getMessage()+(discardDocument(destination)?"":"；请删除所选位置的不完整文件");}
            finally {if(connection!=null)connection.disconnect();if(temporary!=null)temporary.delete();}
            final String message=outcome;
            final boolean complete=saved;
            runOnUiThread(() -> {
                if(isFinishing()||isDestroyed())return;
                progress.dismiss();
                if(!complete){Toast.makeText(this,message,Toast.LENGTH_LONG).show();return;}
                new AlertDialog.Builder(this).setTitle("CSV 已保存").setMessage("文件已保存到你选择的位置。")
                    .setNegativeButton("完成",null).setPositiveButton("打开文件",(dialog,which)->{
                        try {startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(destination,"text/csv").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}
                        catch(Exception ignored){Toast.makeText(this,"没有可打开 CSV 的应用，可在文件管理器中找到已保存的文件",Toast.LENGTH_LONG).show();}
                    }).show();
            });
        });
    }
}
