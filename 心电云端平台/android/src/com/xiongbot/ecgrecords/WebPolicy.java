package com.xiongbot.ecgrecords;

import java.net.URI;

/** One server origin; no file, arbitrary host, userinfo, or encoded traversal. */
public final class WebPolicy {
    public static final String ORIGIN = "https://62.234.150.104";
    public static boolean trusted(String value) {
        try {
            URI uri = new URI(value);
            return "https".equals(uri.getScheme()) && "62.234.150.104".equals(uri.getHost())
                && (uri.getPort() == -1 || uri.getPort() == 443) && uri.getUserInfo() == null;
        } catch (Exception ignored) { return false; }
    }
    public static boolean managementPage(String value) {
        if (!trusted(value)) return false;
        try {
            String path = new URI(value).getPath();
            return "/admin".equals(path) || "/admin/accounts".equals(path)
                || "/devices".equals(path) || "/database".equals(path);
        } catch (Exception ignored) { return false; }
    }
    /** Native credentials/export/printing belong only to the bundled ECG record page. */
    public static boolean recordPage(String value) {
        if (!trusted(value)) return false;
        try {
            String path = new URI(value).getRawPath();
            return "/".equals(path) || "/index.html".equals(path);
        } catch (Exception ignored) { return false; }
    }
    /** External HTTPS navigation goes to the system browser, never this WebView. */
    public static boolean externalPage(String value) {
        try {
            URI uri = new URI(value);
            return "https".equals(uri.getScheme()) && uri.getHost()!=null && uri.getUserInfo()==null
                && (uri.getPort()==-1 || uri.getPort()==443) && !trusted(value);
        } catch (Exception ignored) { return false; }
    }
    public static String asset(String path) {
        if ("/".equals(path) || "/index.html".equals(path)) return "web/index.html";
        if ("/heartlife-connect".equals(path)) return "web/heartlife-connect.html";
        if ("/devices".equals(path)) return "web/device-manager.html";
        if (path == null || !path.startsWith("/assets/")) return null;
        String name = path.substring(8);
        if (!name.matches("[a-zA-Z0-9_./-]+") || name.contains("..") || name.startsWith("/")) return null;
        return "web/" + name;
    }
    public static boolean sessionId(String value) {
        return value != null && value.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,95}");
    }
    private WebPolicy() {}
}
