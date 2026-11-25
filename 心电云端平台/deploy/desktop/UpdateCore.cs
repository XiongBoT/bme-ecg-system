using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

internal enum UpdateKind { NewVersion, Current, Unavailable, Failed }

internal sealed class UpdateResult
{
    internal readonly UpdateKind Kind;
    internal readonly UpdateMetadata Metadata;
    internal UpdateResult(UpdateKind kind,UpdateMetadata metadata=null) {Kind=kind;Metadata=metadata;}
}

internal sealed class UpdateMetadata
{
    internal readonly string VersionText,Notes;
    internal readonly Uri Url;
    private UpdateMetadata(string version,Uri url,string notes) {VersionText=version;Url=url;Notes=notes;}

    internal static bool IsOfficialUrl(string value,string version)
    {
        Uri uri;
        return Uri.TryCreate(value,UriKind.Absolute,out uri) && uri.Scheme==Uri.UriSchemeHttps &&
            uri.Host=="github.com" && uri.IsDefaultPort && uri.UserInfo.Length==0 &&
            uri.Query.Length==0 && uri.Fragment.Length==0 &&
            value=="https://github.com/XiongBoT/bme-ecg-system/releases/tag/desktop-v"+version;
    }

    internal static UpdateResult Parse(string json,Version installed)
    {
        try
        {
            if(String.IsNullOrEmpty(json) || json.Length>16384 || installed==null) return Failed();
            var serializer=new JavaScriptSerializer {MaxJsonLength=16384,RecursionLimit=12};
            var root=serializer.DeserializeObject(json) as Dictionary<string,object>;
            object schema,windows;
            if(root==null || !root.TryGetValue("schema",out schema) || !(schema is int) || (int)schema!=1 ||
                !root.TryGetValue("windows",out windows)) return Failed();
            if(windows==null) return new UpdateResult(UpdateKind.Unavailable);
            var release=windows as Dictionary<string,object>;
            object rawVersion,rawUrl,rawNotes;
            if(release==null || !release.TryGetValue("version",out rawVersion) ||
                !release.TryGetValue("url",out rawUrl) || !release.TryGetValue("notes",out rawNotes)) return Failed();
            string version=rawVersion as string,url=rawUrl as string,notes=rawNotes as string;
            Version latest;
            if(version==null || version.Length>17 || !Regex.IsMatch(version,@"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\z") ||
                !Version.TryParse(version,out latest) || latest.Major>65535 || latest.Minor>65535 || latest.Build>65535 ||
                notes==null || !IsOfficialUrl(url,version)) return Failed();
            var metadata=new UpdateMetadata(version,new Uri(url),PlainNotes(notes));
            return new UpdateResult(Normalized(latest)>Normalized(installed)?UpdateKind.NewVersion:UpdateKind.Current,metadata);
        }
        catch(ArgumentException) {return Failed();}
        catch(InvalidOperationException) {return Failed();}
    }

    private static Version Normalized(Version value)
    {return new Version(value.Major,value.Minor,Math.Max(0,value.Build),Math.Max(0,value.Revision));}
    private static UpdateResult Failed() {return new UpdateResult(UpdateKind.Failed);}
    private static string PlainNotes(string value)
    {
        var result=new StringBuilder();
        foreach(char character in value)
        {
            if(result.Length>=400) break;
            if(Char.IsControl(character) || Char.GetUnicodeCategory(character)==UnicodeCategory.Format) continue;
            result.Append(character);
        }
        if(result.Length>0 && Char.IsHighSurrogate(result[result.Length-1])) result.Length--;
        return result.ToString().Trim();
    }
}

internal static class UpdateProbe
{
    internal const string Endpoint="https://62.234.150.104/api/updates";
    internal static HttpClient CreateClient()
    {
        return new HttpClient(new HttpClientHandler {
            AllowAutoRedirect=false,UseCookies=false,UseDefaultCredentials=false,Credentials=null,PreAuthenticate=false
        }) {Timeout=TimeSpan.FromSeconds(6)};
    }

    internal static async Task<UpdateResult> CheckAsync(HttpClient client,Version installed,CancellationToken token,int timeoutMilliseconds=6000)
    {
        using(var deadline=CancellationTokenSource.CreateLinkedTokenSource(token))
        {
            deadline.CancelAfter(timeoutMilliseconds);
            try
            {
                using(var request=new HttpRequestMessage(HttpMethod.Get,Endpoint))
                using(var response=await Bounded(client.SendAsync(request,HttpCompletionOption.ResponseHeadersRead,deadline.Token),deadline.Token).ConfigureAwait(false))
                {
                    if(response.StatusCode!=HttpStatusCode.OK || response.Content==null || response.Content.Headers.ContentLength>16384)
                        return new UpdateResult(UpdateKind.Failed);
                    using(var stream=await Bounded(response.Content.ReadAsStreamAsync(),deadline.Token).ConfigureAwait(false))
                    using(var body=new MemoryStream())
                    {
                        var buffer=new byte[1024];
                        int count;
                        while((count=await Bounded(stream.ReadAsync(buffer,0,buffer.Length,deadline.Token),deadline.Token).ConfigureAwait(false))>0)
                        {
                            if(body.Length+count>16384) return new UpdateResult(UpdateKind.Failed);
                            body.Write(buffer,0,count);
                        }
                        deadline.Token.ThrowIfCancellationRequested();
                        UpdateResult result=UpdateMetadata.Parse(new UTF8Encoding(false,true).GetString(body.ToArray()),installed);
                        deadline.Token.ThrowIfCancellationRequested();
                        return result;
                    }
                }
            }
            catch(OperationCanceledException) {token.ThrowIfCancellationRequested();return new UpdateResult(UpdateKind.Failed);}
            catch(HttpRequestException) {token.ThrowIfCancellationRequested();return new UpdateResult(UpdateKind.Failed);}
            catch(IOException) {token.ThrowIfCancellationRequested();return new UpdateResult(UpdateKind.Failed);}
            catch(ObjectDisposedException) {token.ThrowIfCancellationRequested();return new UpdateResult(UpdateKind.Failed);}
            catch(DecoderFallbackException) {return new UpdateResult(UpdateKind.Failed);}
        }
    }

    // The deadline covers headers and body, including streams that ignore read cancellation.
    private static async Task<T> Bounded<T>(Task<T> operation,CancellationToken token)
    {
        var cancelled=new TaskCompletionSource<bool>();
        using(token.Register(()=>cancelled.TrySetResult(true)))
        {
            if(await Task.WhenAny(operation,cancelled.Task).ConfigureAwait(false)!=operation)
            {
                ObserveAfterCancellation(operation);
                throw new OperationCanceledException(token);
            }
            T result=await operation.ConfigureAwait(false);
            // When both tasks completed, WhenAny may pick the operation even though time expired.
            if(token.IsCancellationRequested)
            {
                ObserveAfterCancellation(operation);
                throw new OperationCanceledException(token);
            }
            return result;
        }
    }
    private static void ObserveAfterCancellation<T>(Task<T> operation)
    {
        operation.ContinueWith(completed=> {
            if(completed.IsFaulted) {var ignored=completed.Exception;}
            else if(completed.Status==TaskStatus.RanToCompletion)
            {
                var resource=(object)completed.Result as IDisposable;
                if(resource!=null) resource.Dispose();
            }
        },CancellationToken.None,TaskContinuationOptions.ExecuteSynchronously,TaskScheduler.Default);
    }
}

internal sealed class UpdateThrottle
{
    private readonly string path;
    internal UpdateThrottle(string path) {this.path=path;}
    internal static UpdateThrottle ForCurrentUser()
    {
        return new UpdateThrottle(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "BmeEcgWorkspace","update-check.txt"));
    }
    internal bool TryBegin(DateTime now,bool manual)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            // An exclusive file handle also prevents simultaneous launchers checking twice.
            using(var file=new FileStream(path,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None))
            {
                long previous=0;
                if(file.Length<=64)
                {
                    byte[] contents=new byte[(int)file.Length];
                    file.Read(contents,0,contents.Length);
                    Int64.TryParse(Encoding.ASCII.GetString(contents),NumberStyles.None,CultureInfo.InvariantCulture,out previous);
                }
                bool valid=previous>0 && previous<=DateTime.MaxValue.Ticks;
                if(!manual && valid && now.Ticks>=previous && now.Ticks-previous<TimeSpan.TicksPerDay) return false;
                bool clockMovedBack=!manual && valid && now.Ticks<previous;
                byte[] timestamp=Encoding.ASCII.GetBytes(now.Ticks.ToString(CultureInfo.InvariantCulture));
                file.Position=0;file.SetLength(0);file.Write(timestamp,0,timestamp.Length);file.Flush();
                // Rebase a future timestamp, then resume after 24 hours at the corrected clock.
                return !clockMovedBack;
            }
        }
        catch(IOException) {return manual;}
        catch(UnauthorizedAccessException) {return manual;}
        catch(System.Security.SecurityException) {return manual;}
    }
}
