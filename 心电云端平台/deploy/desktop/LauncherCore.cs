using System;
using System.Drawing;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

internal static class LaunchPolicy
{
    internal const string CloudUrl = "https://62.234.150.104/";
    internal static Rectangle WindowBounds(Rectangle area)
    {
        int width = Math.Max(1, Math.Min(1440, area.Width - Math.Min(64, area.Width / 10)));
        int height = Math.Max(1, Math.Min(960, area.Height - Math.Min(64, area.Height / 10)));
        return new Rectangle(area.Left + (area.Width - width) / 2, area.Top + (area.Height - height) / 2, width, height);
    }
    internal static string BrowserArguments(Rectangle area)
    {
        Rectangle bounds = WindowBounds(area);
        return "--app=" + CloudUrl + " --window-size=" + bounds.Width + "," + bounds.Height +
            " --window-position=" + bounds.X + "," + bounds.Y;
    }
    internal static Rectangle ConnectionBounds(Rectangle area, Size preferred)
    {
        int width=Math.Max(1,Math.Min(preferred.Width,area.Width));
        int height=Math.Max(1,Math.Min(preferred.Height,area.Height));
        return new Rectangle(area.Left+(area.Width-width)/2,area.Top+(area.Height-height)/2,width,height);
    }
}

internal sealed class ConnectionGate
{
    private bool running, closed;
    internal bool IsRunning {get{return running && !closed;}}
    internal bool Begin() { if (running || closed) return false; running = true; return true; }
    internal bool Finish() { if (closed || !running) return false; running = false; return true; }
    internal void Close() { closed = true; running = false; }
}

internal enum ConnectionKind { Ready, Timeout, NetworkError, Unavailable }
internal sealed class ConnectionResult
{
    internal readonly ConnectionKind Kind;
    internal readonly string Message;
    internal ConnectionResult(ConnectionKind kind, string message) { Kind = kind; Message = message; }
}

internal static class ConnectionProbe
{
    internal static async Task<ConnectionResult> CheckAsync(HttpClient client, CancellationToken token)
    {
        try
        {
            // Public page only. Do not send cookies, inspect accounts or follow redirects.
            using (var request = new HttpRequestMessage(HttpMethod.Get, LaunchPolicy.CloudUrl))
            using (var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false))
            {
                if (response.StatusCode == HttpStatusCode.OK)
                    return new ConnectionResult(ConnectionKind.Ready, "云端可以连接。请在工作台使用自己的账号登录。");
                return new ConnectionResult(ConnectionKind.Unavailable, "云端暂时没有正常响应。可以稍后重试，或用浏览器查看具体提示。");
            }
        }
        catch (OperationCanceledException)
        {
            if (token.IsCancellationRequested) throw;
            return new ConnectionResult(ConnectionKind.Timeout, "连接等待时间较长。请检查网络，或点击重新连接。");
        }
        catch (HttpRequestException)
        {
            return new ConnectionResult(ConnectionKind.NetworkError, "暂时无法建立安全连接。请检查网络和电脑时间，也可用浏览器查看连接提示。");
        }
    }
}
