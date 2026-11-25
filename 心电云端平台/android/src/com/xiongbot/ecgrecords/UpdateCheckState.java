package com.xiongbot.ecgrecords;

final class UpdateCheckState {
    static final class Result {
        final UpdatePolicy.Release release;
        boolean manual;
        Result(UpdatePolicy.Release release, boolean manual) { this.release = release; this.manual = manual; }
    }
    private boolean running, manual, visible, closed;
    private Result pending;

    // Called only on the Activity's UI thread. A manual request can join an automatic check.
    boolean begin(boolean manual) {
        if (closed) return false;
        if (pending != null) { pending.manual |= manual; return false; }
        if (running) { this.manual |= manual; return false; }
        running = true;
        this.manual = manual;
        return true;
    }
    void complete(UpdatePolicy.Release release) {
        if (closed || !running) return;
        running = false;
        pending = new Result(release, manual);
    }
    void setVisible(boolean visible) { this.visible = visible; }
    Result takePending() {
        if (closed || !visible) return null;
        Result result = pending;
        pending = null;
        return result;
    }
    void close() { closed = true; running = false; pending = null; }
}
