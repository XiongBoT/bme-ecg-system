package com.xiongbot.ecgrecords;

public final class UpdateCheckStateTest {
    private static int checked;
    private static void check(boolean condition, String message) {
        checked++;
        if (!condition) throw new AssertionError(message);
    }
    public static void main(String[] args) {
        UpdatePolicy.Release release = UpdatePolicy.release("1.2.3", 4,
            "https://github.com/XiongBoT/bme-ecg-system/releases/tag/android-v1.2.3", "");
        UpdateCheckState state = new UpdateCheckState();
        check(state.begin(false), "first automatic check starts");
        check(!state.begin(false), "duplicate automatic request blocked");
        check(!state.begin(true), "manual check joins existing request");
        state.complete(release);
        check(state.takePending() == null, "background result waits while paused");
        state.setVisible(true);
        UpdateCheckState.Result result = state.takePending();
        check(result != null && result.release == release && result.manual, "joined manual check gets visible result");
        check(state.takePending() == null, "result only delivered once");
        state.complete(release);
        check(state.takePending() == null, "late duplicate completion ignored");
        check(state.begin(false), "next check can start");
        state.setVisible(false);
        state.complete(null);
        check(!state.begin(true), "manual check can use pending result without duplicate request");
        state.setVisible(true);
        result = state.takePending();
        check(result != null && result.release == null && result.manual, "unavailable is explicit and manual status retained");
        check(state.begin(false), "in-flight check starts before destroy");
        state.close();
        state.complete(release);
        state.setVisible(true);
        check(state.takePending() == null, "destroyed Activity ignores late callback");
        check(!state.begin(true), "destroyed Activity cannot start check");
        UpdateCheckState pending = new UpdateCheckState();
        pending.begin(false);
        pending.complete(release);
        pending.close();
        pending.setVisible(true);
        check(pending.takePending() == null, "destroy also discards a queued dialog");
        System.out.println("UpdateCheckState: " + checked + " cases passed");
    }
}
