package com.xiongbot.ecgrecords;

import java.net.URI;

final class UpdatePolicy {
    private static final long CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000;
    static final class Release {
        final String version, url, notes;
        final long versionCode;
        private Release(String version, long versionCode, String url, String notes) {
            this.version = version;
            this.versionCode = versionCode;
            this.url = url;
            this.notes = notes;
        }
        boolean isNewerThan(long installed) { return installed > 0 && versionCode > installed; }
    }
    static Release release(Object version, Object code, Object url, Object notes) {
        if (!(version instanceof String) || !(url instanceof String) || !(notes instanceof String)) return null;
        if (!integer(code) || ((Number)code).longValue() <= 0 || ((Number)code).longValue() > Integer.MAX_VALUE) return null;
        String name = (String)version, address = (String)url, description = (String)notes;
        if (!name.matches("(?:0|[1-9][0-9]{0,8})\\.(?:0|[1-9][0-9]{0,8})\\.(?:0|[1-9][0-9]{0,8})")) return null;
        if (description.length() > 1000) return null;
        for (int i = 0; i < description.length(); i++) {
            char c = description.charAt(i);
            if ((Character.isISOControl(c) && c != '\n' && c != '\r' && c != '\t') || Character.getType(c) == Character.FORMAT) return null;
        }
        try {
            URI parsed = new URI(address);
            if (!"https".equals(parsed.getScheme()) || !"github.com".equals(parsed.getHost()) || parsed.getRawUserInfo() != null ||
                (parsed.getPort() != -1 && parsed.getPort() != 443) || parsed.getRawQuery() != null || parsed.getRawFragment() != null) return null;
            if (!"github.com".equals(parsed.getRawAuthority()) && !"github.com:443".equals(parsed.getRawAuthority())) return null;
            String expected = "/XiongBoT/bme-ecg-system/releases/tag/android-v" + name;
            String path = parsed.getRawPath();
            if (!expected.equals(path) && !(path != null && path.startsWith(expected + "-preview.") &&
                path.substring(expected.length()).matches("-preview\\.[1-9][0-9]{0,8}"))) return null;
            return new Release(name, ((Number)code).longValue(), address, description);
        } catch (Exception ignored) { return null; }
    }
    private static boolean integer(Object value) { return value instanceof Integer || value instanceof Long; }
    static boolean schemaSupported(Object schema) { return integer(schema) && ((Number)schema).longValue() == 1; }
    static boolean shouldCheck(long now, long last) {
        // A backwards clock must not suppress checks until an old future timestamp catches up.
        return now >= 0 && (last < 0 || now < last || now - last >= CHECK_INTERVAL_MS);
    }
}
