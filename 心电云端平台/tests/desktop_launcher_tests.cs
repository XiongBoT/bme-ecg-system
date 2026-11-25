using System;
using System.Drawing;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

internal static class DesktopLauncherTests
{
    private sealed class Handler : HttpMessageHandler
    {
        internal HttpStatusCode Status = HttpStatusCode.OK;
        internal bool Timeout;
        internal bool NetworkError;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Check(request.Method == HttpMethod.Get && request.RequestUri.AbsoluteUri == LaunchPolicy.CloudUrl, "fixed public GET");
            Check(request.Headers.Authorization == null, "no credentials");
            token.ThrowIfCancellationRequested();
            if (Timeout) throw new TaskCanceledException();
            if (NetworkError) throw new HttpRequestException("private diagnostics must not be shown");
            return Task.FromResult(new HttpResponseMessage(Status));
        }
    }
    private static void Check(bool value, string label) { if (!value) {Console.Error.WriteLine(label);throw new Exception(label);} }
    private static int Main()
    {
        DesktopUpdateTests.Run();
        foreach (Rectangle screen in new[] {new Rectangle(0,0,1366,728), new Rectangle(-1920,0,1920,1040), new Rectangle(0,0,800,560)})
        {
            Rectangle bounds = LaunchPolicy.WindowBounds(screen);
            Check(screen.Contains(bounds), "window stays inside working area");
            Check(bounds.Width > 0 && bounds.Height > 0, "positive window");
            string arguments = LaunchPolicy.BrowserArguments(screen);
            Check(arguments.Contains("--app=" + LaunchPolicy.CloudUrl), "fixed origin");
            Check(!arguments.Contains("ignore-certificate") && !arguments.Contains("user-data-dir"), "browser security unchanged");
        }
        var gate = new ConnectionGate();
        foreach(Rectangle screen in new[]{new Rectangle(0,0,512,344),new Rectangle(-640,0,640,360),new Rectangle(0,0,1366,728)})
            Check(screen.Contains(LaunchPolicy.ConnectionBounds(screen,new Size(1140,770))),"scaled connection window stays on screen");
        Check(gate.Begin(), "first check starts");Check(!gate.Begin(), "duplicate check rejected");
        Check(gate.Finish(), "active response accepted");Check(gate.Begin(), "retry available");
        gate.Close();Check(!gate.Finish() && !gate.Begin(), "closed window rejects late response");
        var handler = new Handler();
        using (var client = new HttpClient(handler))
        {
            Check(ConnectionProbe.CheckAsync(client, CancellationToken.None).GetAwaiter().GetResult().Kind == ConnectionKind.Ready, "200 ready");
            handler.Status = HttpStatusCode.Redirect;
            Check(ConnectionProbe.CheckAsync(client, CancellationToken.None).GetAwaiter().GetResult().Kind == ConnectionKind.Unavailable, "redirect not ready");
            handler.Status = HttpStatusCode.ServiceUnavailable;
            Check(ConnectionProbe.CheckAsync(client, CancellationToken.None).GetAwaiter().GetResult().Kind == ConnectionKind.Unavailable, "503 unavailable");
            handler.Timeout = true;
            Check(ConnectionProbe.CheckAsync(client, CancellationToken.None).GetAwaiter().GetResult().Kind == ConnectionKind.Timeout, "bounded wait");
            handler.Timeout = false;handler.NetworkError = true;
            var failure = ConnectionProbe.CheckAsync(client, CancellationToken.None).GetAwaiter().GetResult();
            Check(failure.Kind == ConnectionKind.NetworkError && !failure.Message.Contains("private diagnostics"), "safe connection error");
            var cancelled = new CancellationTokenSource();cancelled.Cancel();
            try {ConnectionProbe.CheckAsync(client, cancelled.Token).GetAwaiter().GetResult();throw new Exception("cancel ignored");}
            catch (OperationCanceledException) { }
        }
        Console.WriteLine("Window, request, timeout, retry and close checks passed");
        return 0;
    }
}
