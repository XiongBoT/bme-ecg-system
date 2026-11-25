package com.xiongbot.ecgrecords;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.cert.Certificate;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import javax.net.ssl.HttpsURLConnection;

public final class UpdateClientTest {
    private static int checked;
    private static void check(boolean condition, String message) {
        checked++;
        if (!condition) throw new AssertionError(message);
    }
    private static void rejected(InputStream stream, long length, String message) throws Exception {
        try { UpdateClient.readBody(stream, length); throw new AssertionError(message); }
        catch (IOException expected) { checked++; }
    }
    private static class Response extends HttpsURLConnection {
        final byte[] body;
        final int status;
        final String type;
        boolean opened;
        Response(int status, String type, byte[] body) throws Exception {
            super(new URL("https://62.234.150.104/api/updates"));
            this.status = status; this.type = type; this.body = body;
        }
        @Override public int getResponseCode() { return status; }
        @Override public String getContentType() { return type; }
        @Override public long getContentLengthLong() { return body.length; }
        @Override public InputStream getInputStream() { opened = true; return new ByteArrayInputStream(body); }
        @Override public void connect() { }
        @Override public void disconnect() { }
        @Override public boolean usingProxy() { return false; }
        @Override public String getCipherSuite() { return "TLS"; }
        @Override public Certificate[] getLocalCertificates() { return null; }
        @Override public Certificate[] getServerCertificates() { return null; }
    }
    private static void rejectResponse(Response response) throws Exception {
        try { UpdateClient.readResponse(response); throw new AssertionError("invalid HTTP response accepted"); }
        catch (IOException expected) { check(!response.opened, "invalid response must not read body"); }
    }
    private static final class DripResponse extends Response {
        final CountDownLatch disconnected = new CountDownLatch(1);
        int chunks;
        DripResponse() throws Exception { super(200, "application/json", "{}       ".getBytes(StandardCharsets.UTF_8)); }
        @Override public InputStream getInputStream() {
            opened = true;
            return new InputStream() {
                @Override public int read() throws IOException {
                    if (chunks == body.length) return -1;
                    try {
                        // Every chunk arrives well within the socket's six-second read timeout.
                        if (disconnected.await(800, TimeUnit.MILLISECONDS)) throw new IOException("disconnected");
                    } catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException(e); }
                    return body[chunks++];
                }
                @Override public int read(byte[] target, int offset, int length) throws IOException {
                    int next = read();
                    if (next < 0) return -1;
                    target[offset] = (byte)next;
                    return 1;
                }
            };
        }
        @Override public void disconnect() { disconnected.countDown(); }
    }
    private static final class LateResponse extends Response {
        final CountDownLatch disconnected = new CountDownLatch(1);
        LateResponse() throws Exception { super(200, "application/json", "{}".getBytes(StandardCharsets.UTF_8)); }
        @Override public int getResponseCode() {
            try { disconnected.await(6500, TimeUnit.MILLISECONDS); }
            catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
            // A transport may still return a buffered successful response after cancellation.
            return 200;
        }
        @Override public void disconnect() { disconnected.countDown(); }
    }
    private static void deadlineStopsDripAndLateSuccess() throws Exception {
        DripResponse drip = new DripResponse();
        long started = System.nanoTime();
        try { UpdateClient.readResponse(drip); throw new AssertionError("drip-fed response escaped whole-request deadline"); }
        catch (IOException expected) {
            check(drip.chunks >= 2 && drip.chunks < drip.body.length, "deadline ends an active drip response before all chunks arrive");
            check(drip.disconnected.getCount() == 0, "deadline disconnects the network operation");
            check(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started) < 7000, "whole request completes near six seconds");
        }
        LateResponse late = new LateResponse();
        try { UpdateClient.readResponse(late); throw new AssertionError("late 200 response was delivered as success"); }
        catch (IOException expected) {
            check(late.disconnected.getCount() == 0, "late response was actively cancelled");
            check(!late.opened, "expired response cannot deliver its valid body to the callback");
        }
    }
    public static void main(String[] args) throws Exception {
        byte[] text = "{\"notes\":\"新版\"}".getBytes(StandardCharsets.UTF_8);
        check("{\"notes\":\"新版\"}".equals(UpdateClient.readBody(new ByteArrayInputStream(text), -1)), "UTF-8 body preserved");
        check(UpdateClient.readBody(new ByteArrayInputStream(new byte[16384]), 16384).length() == 16384, "exact limit allowed");
        rejected(new ByteArrayInputStream(new byte[16385]), -1, "streamed body above limit rejected");
        rejected(new ByteArrayInputStream(text), 16385, "oversized declared body rejected before reading");
        rejected(new ByteArrayInputStream(text), text.length + 1, "truncated response rejected");
        rejected(new ByteArrayInputStream(text), text.length - 1, "incorrect length rejected");
        rejected(new ByteArrayInputStream(new byte[]{(byte)0xc3, 0x28}), -1, "malformed UTF-8 rejected");
        rejected(new InputStream() {
            @Override public int read() throws IOException { throw new IOException("connection lost"); }
        }, -1, "network read failures propagated");
        Thread.currentThread().interrupt();
        try { rejected(new ByteArrayInputStream(text), -1, "cancelled read rejected"); }
        finally { Thread.interrupted(); }
        Response response = new Response(200, "application/json; charset=utf-8", text);
        check("{\"notes\":\"新版\"}".equals(UpdateClient.readResponse(response)), "valid JSON response read");
        check(!response.getInstanceFollowRedirects(), "redirects disabled before connecting");
        check(response.getConnectTimeout() == 6000 && response.getReadTimeout() == 6000, "both network timeouts bounded");
        check(!response.getUseCaches(), "version responses cannot use cached connection data");
        check("application/json".equals(response.getRequestProperty("Accept")), "request JSON only");
        check("identity".equals(response.getRequestProperty("Accept-Encoding")), "response cap applies to uncompressed bytes");
        check(response.getRequestProperty("Cookie") == null && response.getRequestProperty("Authorization") == null,
            "public update request contains no account credentials");
        for (int status : new int[]{301, 302, 307, 308, 401, 404, 500}) rejectResponse(new Response(status, "application/json", text));
        rejectResponse(new Response(200, null, text));
        rejectResponse(new Response(200, "text/html", text));
        rejectResponse(new Response(200, "application/jsonp", text));
        rejectResponse(new Response(200, "application/json", new byte[16385]));
        UpdateClient closed = new UpdateClient();
        closed.close();
        try { closed.fetch(); throw new AssertionError("closed client attempted a network request"); }
        catch (IOException expected) { checked++; }
        deadlineStopsDripAndLateSuccess();
        System.out.println("UpdateClient: " + checked + " cases passed");
    }
}
