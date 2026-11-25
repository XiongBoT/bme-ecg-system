package com.xiongbot.ecgrecords;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.HttpsURLConnection;

final class UpdateClient {
    private static final int MAX_RESPONSE_BYTES = 16 * 1024;
    private static final int REQUEST_TIMEOUT_MS = 6000;
    private volatile boolean closed;
    private volatile HttpsURLConnection active;

    String fetch() throws IOException {
        if (closed) throw new IOException("Update check cancelled");
        HttpsURLConnection connection = (HttpsURLConnection)new URL(WebPolicy.ORIGIN + "/api/updates").openConnection();
        active = connection;
        try {
            if (closed || Thread.currentThread().isInterrupted()) throw new IOException("Update check cancelled");
            String body = readResponse(connection);
            if (closed) throw new IOException("Update check cancelled");
            return body;
        } finally {
            active = null;
            connection.disconnect();
        }
    }

    void close() {
        closed = true;
        HttpsURLConnection connection = active;
        if (connection != null) connection.disconnect();
    }

    static String readResponse(HttpsURLConnection connection) throws IOException {
        try (RequestDeadline deadline = new RequestDeadline(connection)) {
            // Separate from WebView networking: never read or attach its cookies or account data.
            // Keep the platform trust manager and hostname verifier unchanged.
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(REQUEST_TIMEOUT_MS);
            connection.setReadTimeout(REQUEST_TIMEOUT_MS);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Accept-Encoding", "identity");
            connection.setRequestProperty("Cache-Control", "no-store");
            int status = connection.getResponseCode();
            deadline.check();
            if (status != 200) throw new IOException("Update service unavailable");
            String type = connection.getContentType();
            if (type == null || !"application/json".equalsIgnoreCase(type.split(";", 2)[0].trim()))
                throw new IOException("Invalid update response type");
            long length = connection.getContentLengthLong();
            if (length > MAX_RESPONSE_BYTES) throw new IOException("Update response too large");
            String body;
            try (InputStream input = connection.getInputStream()) { body = readBody(input, length, deadline); }
            deadline.complete();
            return body;
        }
    }

    static String readBody(InputStream input, long length) throws IOException {
        return readBody(input, length, null);
    }

    private static String readBody(InputStream input, long length, RequestDeadline deadline) throws IOException {
        if (length > MAX_RESPONSE_BYTES) throw new IOException("Update response too large");
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[2048];
        while (true) {
            if (Thread.currentThread().isInterrupted()) throw new IOException("Update check cancelled");
            if (deadline != null) deadline.check();
            int count = input.read(buffer);
            if (deadline != null) deadline.check();
            if (count == -1) break;
            if (output.size() + count > MAX_RESPONSE_BYTES) throw new IOException("Update response too large");
            output.write(buffer, 0, count);
        }
        if (length >= 0 && output.size() != length) throw new IOException("Incomplete update response");
        return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(output.toByteArray())).toString();
    }

    private static final class RequestDeadline implements AutoCloseable {
        private final HttpsURLConnection connection;
        private final long started = System.nanoTime();
        // 0 = active, 1 = expired, 2 = finished. A late response cannot undo expiration.
        private final AtomicInteger state = new AtomicInteger();
        private final ScheduledExecutorService timer = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread worker = new Thread(task, "ECG update deadline");
            worker.setDaemon(true);
            return worker;
        });

        RequestDeadline(HttpsURLConnection connection) {
            this.connection = connection;
            timer.schedule(this::expire, REQUEST_TIMEOUT_MS, TimeUnit.MILLISECONDS);
        }
        private void expire() {
            if (state.compareAndSet(0, 1)) connection.disconnect();
        }
        void check() throws IOException {
            if (state.get() == 1 || System.nanoTime() - started >= TimeUnit.MILLISECONDS.toNanos(REQUEST_TIMEOUT_MS)) {
                expire();
                throw new SocketTimeoutException("Update request deadline exceeded");
            }
        }
        void complete() throws IOException {
            check();
            if (!state.compareAndSet(0, 2)) throw new SocketTimeoutException("Update request deadline exceeded");
        }
        @Override public void close() {
            state.compareAndSet(0, 2);
            // Each request owns and closes its timer, including error and Activity-destroy paths.
            timer.shutdownNow();
        }
    }
}
