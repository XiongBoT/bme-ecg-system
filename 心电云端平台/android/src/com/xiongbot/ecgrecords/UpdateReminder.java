package com.xiongbot.ecgrecords;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;
import org.json.JSONTokener;

/** Native update notices only; it never downloads an APK or shares WebView credentials. */
final class UpdateReminder {
    private final Activity activity;
    private final SharedPreferences preferences;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final UpdateClient client = new UpdateClient();
    private final UpdateCheckState state = new UpdateCheckState();
    private final long installedCode;
    private boolean resumed, closed;
    private AlertDialog dialog;

    UpdateReminder(Activity activity) {
        this.activity = activity;
        preferences = activity.getSharedPreferences("update-reminders", Context.MODE_PRIVATE);
        long code = 0;
        try {
            PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
            code = Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
        } catch (Exception ignored) { }
        installedCode = code;
    }

    void onResume() { resumed = true; showPending(); check(false); }
    void onPause() { resumed = false; state.setVisible(false); }
    void onWindowFocusChanged(boolean focused) {
        state.setVisible(resumed && focused);
        if (focused) showPending();
    }
    void checkManually() { check(true); }

    private void check(boolean manual) {
        if (closed || activity.isFinishing() || activity.isDestroyed()) return;
        if (dialog != null) return;
        long now = System.currentTimeMillis();
        if (!manual && !UpdatePolicy.shouldCheck(now, preferences.getLong("last-attempt", -1L))) return;
        if (manual) Toast.makeText(activity, "正在检查更新…", Toast.LENGTH_SHORT).show();
        if (!state.begin(manual)) { showPending(); return; }
        // Record attempts, including failures, so offline resumes cannot create a request loop.
        preferences.edit().putLong("last-attempt", now).apply();
        network.execute(() -> {
            UpdatePolicy.Release found = null;
            try {
                JSONTokener tokener = new JSONTokener(client.fetch());
                Object value = tokener.nextValue();
                if (value instanceof JSONObject && tokener.nextClean() == 0) {
                    JSONObject document = (JSONObject)value;
                    Object android = document.opt("android");
                    if (UpdatePolicy.schemaSupported(document.opt("schema")) && android instanceof JSONObject) {
                        JSONObject release = (JSONObject)android;
                        found = UpdatePolicy.release(release.opt("version"), release.opt("version_code"),
                            release.opt("url"), release.opt("notes"));
                    }
                }
            } catch (Exception ignored) { }
            final UpdatePolicy.Release release = found;
            main.post(() -> {
                if (closed) return;
                state.complete(release);
                showPending();
            });
        });
    }

    private void showPending() {
        boolean visible = resumed && activity.hasWindowFocus() && !activity.isFinishing() && !activity.isDestroyed();
        state.setVisible(visible);
        if (closed || !visible || dialog != null) return;
        UpdateCheckState.Result result = state.takePending();
        if (result == null) return;
        UpdatePolicy.Release release = result.release;
        if (release == null || installedCode <= 0) {
            if (result.manual) Toast.makeText(activity, "暂时无法获取可用版本信息，请稍后重试。", Toast.LENGTH_LONG).show();
            return;
        }
        if (!release.isNewerThan(installedCode)) {
            if (result.manual) Toast.makeText(activity, "暂未发现比当前版本更新的可用版本。", Toast.LENGTH_LONG).show();
            return;
        }
        String message = "可用版本：" + release.version;
        if (!release.notes.isEmpty()) message += "\n\n" + release.notes;
        message += "\n\n查看新版将打开项目发布页，由你自行选择下载和安装。";
        dialog = new AlertDialog.Builder(activity).setTitle("发现新版本").setMessage(message)
            .setNegativeButton("稍后", null).setPositiveButton("查看新版", (d, which) -> {
                try { activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(release.url)).addCategory(Intent.CATEGORY_BROWSABLE)); }
                catch (Exception ignored) { Toast.makeText(activity, "无法打开浏览器，请稍后重试。", Toast.LENGTH_LONG).show(); }
            }).create();
        dialog.setOnDismissListener(d -> dialog = null);
        dialog.show();
    }

    void close() {
        closed = true;
        state.close();
        client.close();
        network.shutdownNow();
        main.removeCallbacksAndMessages(null);
        if (dialog != null) { dialog.dismiss(); dialog = null; }
    }
}
