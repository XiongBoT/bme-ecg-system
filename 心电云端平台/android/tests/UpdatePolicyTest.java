package com.xiongbot.ecgrecords;

public final class UpdatePolicyTest {
    private static int checked;
    private static final String RELEASE = "https://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.2.3";
    private static void check(boolean value, String message) {
        checked++;
        if (!value) throw new AssertionError(message);
    }
    private static void invalid(Object version, Object code, Object url, Object notes) {
        check(UpdatePolicy.release(version, code, url, notes) == null, "must reject release: " + url);
    }
    public static void main(String[] args) {
        UpdatePolicy.Release release = UpdatePolicy.release("1.2.3", 4, RELEASE, "修复问题\n改善连接");
        check(release != null, "valid official release must be accepted");
        check(release.isNewerThan(3), "larger versionCode must notify");
        check(!release.isNewerThan(4), "same versionCode must not notify");
        check(!release.isNewerThan(5), "older versionCode must not notify");
        check(!release.isNewerThan(0), "unknown installed version must not imply upgrade");
        check(UpdatePolicy.release("0.0.1", 4L, RELEASE.replace("1.2.3", "0.0.1"), "") != null,
            "versionCode is authoritative even when display version is smaller");
        check(UpdatePolicy.release("1.2.3", 4L, RELEASE + "-preview.1", "") != null, "official preview allowed");
        check(UpdatePolicy.release("1.2.3", 4, RELEASE.replace("github.com/", "github.com:443/"), "") != null,
            "default HTTPS port allowed");
        check(UpdatePolicy.release("65535.65535.65535", 4, RELEASE.replace("1.2.3", "65535.65535.65535"), "") != null,
            "each display-version component accepts the contract maximum");
        for (String version : new String[]{"65536.0.0", "0.65536.0", "0.0.65536", "999999999.0.0", "999999999999999999999999.0.0"})
            invalid(version, 4, RELEASE.replace("1.2.3", version), "");
        for (Object code : new Object[]{null, "4", 4.0, true, 0, -1, 2147483648L}) invalid("1.2.3", code, RELEASE, "");
        for (Object version : new Object[]{null, 123, "", "01.2.3", "1.2", "1.2.3.4", "1.2.3-beta", "1.2.3\n", "1.2.3/../4"})
            invalid(version, 4, RELEASE, "");
        for (Object url : new Object[]{null, 1, "http://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.2.3",
            RELEASE.replace("github.com", "github.com.evil.test"), RELEASE.replace("github.com", "evil.test@github.com"),
            RELEASE.replace("github.com", "github.com:444"), RELEASE.replace("github.com", "github.com:"),
            RELEASE.replace("github.com", "github.com:0443"), RELEASE + "?download=1", RELEASE + "#notes", RELEASE + "/",
            RELEASE + "-preview.0", RELEASE + "-preview.01", RELEASE.replace("1.2.3", "1.2.4"),
            RELEASE.replace("android-v", "windows-v"), RELEASE.replace("XiongBoT", "someone"),
            RELEASE.replace("android-v1", "android-v%31"), RELEASE.replace("/releases/", "/other/../releases/"),
            "javascript:alert(1)", "//github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.2.3"}) invalid("1.2.3", 4, url, "");
        invalid("1.2.3", 4, RELEASE, null);
        invalid("1.2.3", 4, RELEASE, 12);
        invalid("1.2.3", 4, RELEASE, "bad\u0000text");
        invalid("1.2.3", 4, RELEASE, "bad\u202Etext");
        invalid("1.2.3", 4, RELEASE, new String(new char[1001]).replace('\0', 'x'));
        check(UpdatePolicy.schemaSupported(1) && UpdatePolicy.schemaSupported(1L), "schema 1 supported");
        for (Object schema : new Object[]{null, "1", 1.0, true, 0, 2}) check(!UpdatePolicy.schemaSupported(schema), "invalid schema rejected");
        check(UpdatePolicy.shouldCheck(1000L, -1L), "first use checks");
        check(!UpdatePolicy.shouldCheck(1000L, 1000L), "same instant throttled");
        check(!UpdatePolicy.shouldCheck(86400999L, 1000L), "before 24 hours throttled");
        check(UpdatePolicy.shouldCheck(86401000L, 1000L), "24 hour boundary checks");
        check(UpdatePolicy.shouldCheck(500L, 1000L), "clock rollback recovers instead of permanent suppression");
        check(!UpdatePolicy.shouldCheck(-1L, 1000L), "invalid current clock cannot check");
        check(UpdatePolicy.shouldCheck(Long.MAX_VALUE, 1000L), "long elapsed interval cannot overflow");
        System.out.println("UpdatePolicy: " + checked + " cases passed");
    }
}
